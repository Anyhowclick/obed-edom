"""Unit tests for `scripts/continuity_core_variants.py`, the probe-only red controls
(plan `keynote_live_continuity_generalisation.plan.md` §3 S1, §4).

Each core variant is a string transform of today's `PRESERVE_CORE_JS` anchored on text
that must occur exactly once, so these tests pin the anchors: when the core moves (S2),
the variant must fail loudly rather than inject today's bytes under a variant's name.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for sub in ("scripts", "src"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import continuity_core_variants as variants  # noqa: E402
from obed_edom.live_continuity_js import PRESERVE_CORE_JS, js_sha256  # noqa: E402


def test_the_variant_names_are_the_shared_contract() -> None:
    assert variants.VARIANTS == ("stash-any", "wrong-instance", "fifo-reuse", "linear-bridge")


@pytest.mark.parametrize("name", variants.VARIANTS)
def test_each_anchor_occurs_exactly_once_in_todays_core(name: str) -> None:
    anchor, _ = variants._TRANSFORMS[name]
    assert PRESERVE_CORE_JS.count(anchor) == 1


@pytest.mark.parametrize("name", ["stash-any", "wrong-instance", "linear-bridge"])
def test_a_red_variant_differs_from_the_core(name: str) -> None:
    core = variants.variant_core(name)
    assert core != PRESERVE_CORE_JS
    assert variants.variant_sha(name) != js_sha256()


def test_stash_any_drops_only_the_plan_asset_filter() -> None:
    core = variants.variant_core("stash-any")
    assert "if (!movieAssetKey(src)) return;" not in core
    assert "v.__obedMovieKey = movieAssetKey(src);" in core
    assert len(PRESERVE_CORE_JS) - len(core) == len("    if (!movieAssetKey(src)) return;\n")


def test_wrong_instance_takes_the_newest_pooled_decoder() -> None:
    core = variants.variant_core("wrong-instance")
    assert "const cand = q.pop();" in core
    assert "const cand = q.shift();" not in core
    # The restart-zone retire loop keeps its own shift: only the reuse pick changes.
    assert core.count("retireDecoder(q.shift())") == PRESERVE_CORE_JS.count("retireDecoder(q.shift())") == 1


def test_linear_bridge_restores_only_the_linear_overlay_progress() -> None:
    """The bridge overlay's red control: progress back to clamped linear time, while the
    eased evaluator stays defined (unused) so nothing else in the core moves."""
    core = variants.variant_core("linear-bridge")
    linear = "const progress = Math.min(1, Math.max(0, (performance.now() - started) / (1000 * boundary.durationSeconds)));"
    assert core.count(linear) == 1
    assert "easeInEaseOut((performance.now()" not in core
    assert core.count("function easeInEaseOut(p)") == PRESERVE_CORE_JS.count("function easeInEaseOut(p)") == 1
    assert core.replace(linear, variants._TRANSFORMS["linear-bridge"][0]) == PRESERVE_CORE_JS


def test_linear_bridge_moves_the_overlay_linearly_in_the_real_core(monkeypatch) -> None:
    """The variant is a behavioural red, not just different bytes: injected in place of
    the core, the bridge overlay lands on the linear rect at .25/.75."""
    from test_live_continuity_js import _BRIDGE_DEST, _BRIDGE_SRC, _bridge_overlay_rects

    from obed_edom import live_continuity_js

    monkeypatch.setattr(live_continuity_js, "PRESERVE_CORE_JS", variants.variant_core("linear-bridge"))
    result = _bridge_overlay_rects()
    for fraction, rect in zip((0, 0.25, 0.5, 0.75, 1), result["rects"]):
        linear = {k: _BRIDGE_SRC[k] + (_BRIDGE_DEST[k] - _BRIDGE_SRC[k]) * fraction for k in _BRIDGE_SRC}
        assert rect == pytest.approx(linear), fraction


def test_fifo_reuse_is_todays_core_byte_for_byte() -> None:
    assert variants.variant_core("fifo-reuse") == PRESERVE_CORE_JS
    assert variants.variant_sha("fifo-reuse") == js_sha256()


@pytest.mark.parametrize("name", variants.VARIANTS)
def test_a_core_without_the_anchor_raises_naming_variant_and_anchor(name: str) -> None:
    anchor, _ = variants._TRANSFORMS[name]
    with pytest.raises(ValueError) as caught:
        variants.variant_core(name, PRESERVE_CORE_JS.replace(anchor, ""))
    assert name in str(caught.value) and anchor.strip() in str(caught.value)


@pytest.mark.parametrize("name", variants.VARIANTS)
def test_a_core_with_the_anchor_twice_raises(name: str) -> None:
    anchor, _ = variants._TRANSFORMS[name]
    with pytest.raises(ValueError, match="2 times"):
        variants.variant_core(name, PRESERVE_CORE_JS + anchor)


def test_an_unknown_variant_raises() -> None:
    with pytest.raises(ValueError, match="unknown core variant"):
        variants.variant_core("lifo")


RUNTIME = {
    "movies": {"movie1": {"assetKeys": ["untitled.mov"]}},
    "boundaries": [
        {"atScene": 2, "action": "retire", "movieKey": "movie1"},
        {"atScene": 6, "action": "restart"},
        {"atScene": 8, "action": "bridge", "movieKey": "movie1"},
        {"atScene": 10, "action": "restart"},
    ],
}


def test_strip_drops_every_entry_of_the_action_without_a_scene() -> None:
    stripped = variants.strip_entries(RUNTIME, "restart")
    assert [(b["atScene"], b["action"]) for b in stripped["boundaries"]] == [(2, "retire"), (8, "bridge")]


def test_strip_at_a_scene_drops_only_that_entry() -> None:
    stripped = variants.strip_entries(RUNTIME, "restart", 6)
    assert [(b["atScene"], b["action"]) for b in stripped["boundaries"]] == [(2, "retire"), (8, "bridge"), (10, "restart")]


def test_strip_is_a_deep_copy_and_leaves_the_input_alone() -> None:
    before = copy.deepcopy(RUNTIME)
    stripped = variants.strip_entries(RUNTIME, "bridge", 8)
    stripped["movies"]["movie1"]["assetKeys"].append("x")
    assert RUNTIME == before


@pytest.mark.parametrize(("action", "scene"), [("pin", None), ("bridge", 6), ("glReplay", 2)])
def test_strip_raises_when_nothing_matches(action: str, scene: int | None) -> None:
    with pytest.raises(ValueError, match="no "):
        variants.strip_entries(RUNTIME, action, scene)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("bridge@8", ("bridge", 8)), ("retire", ("retire", None)), ("glReplay@2", ("glReplay", 2)), (" restart@6 ", ("restart", 6))],
)
def test_parse_strip(value: str, expected: tuple[str, int | None]) -> None:
    assert variants.parse_strip(value) == expected


@pytest.mark.parametrize("value", ["", "@8", "bridge@", "bridge@x", "bridge@8@9", "bri dge"])
def test_parse_strip_rejects_malformed(value: str) -> None:
    with pytest.raises(ValueError):
        variants.parse_strip(value)
