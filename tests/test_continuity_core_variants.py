"""Unit tests for `scripts/continuity_core_variants.py`, the probe-only red controls
(plan `keynote_live_continuity_generalisation.plan.md` §3 S1, §4).

Each core variant is a set of string transforms of the v6 `PRESERVE_CORE_JS`, each anchored on
text that must occur exactly once, so these tests pin the anchors: when the core moves, the
variant must fail loudly rather than inject the core's bytes under a variant's name.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
for sub in ("scripts", "src"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import continuity_core_variants as variants  # noqa: E402
from obed_edom.live_continuity_js import PRESERVE_CORE_JS, js_sha256  # noqa: E402


def test_the_variant_names_are_the_shared_contract() -> None:
    assert variants.VARIANTS == ("stash-any", "wrong-instance", "fifo-reuse")


ANCHORS = [(name, anchor) for name in variants.VARIANTS for anchor, _ in variants._TRANSFORMS[name]]


@pytest.mark.parametrize(("name", "anchor"), ANCHORS)
def test_each_anchor_occurs_exactly_once_in_todays_core(name: str, anchor: str) -> None:
    assert PRESERVE_CORE_JS.count(anchor) == 1


@pytest.mark.parametrize("name", variants.VARIANTS)
def test_every_variant_differs_from_the_core_and_reports_its_own_sha(name: str) -> None:
    core = variants.variant_core(name)
    assert core != PRESERVE_CORE_JS
    assert variants.variant_sha(name) != js_sha256()
    assert len({variants.variant_sha(n) for n in variants.VARIANTS}) == len(variants.VARIANTS)


def test_stash_any_drops_the_plan_asset_and_the_planned_instance_filters() -> None:
    core = variants.variant_core("stash-any")
    assert "if (!movieAssetKey(src)) return;" not in core
    assert "if (!armedPool && !poolable(v)) return;" not in core
    assert "v.__obedMovieKey = movieAssetKey(src);" in core
    assert "function poolable(v)" in core and "return c.__obedInstance === entry.src.objectId;" in core


@pytest.mark.parametrize("name", ["wrong-instance", "fifo-reuse"])
def test_the_pick_variants_pool_every_plan_asset_instance_and_filter_by_asset(name: str) -> None:
    core = variants.variant_core(name)
    assert "if (!movieAssetKey(src)) return;" in core
    assert "if (!armedPool && !poolable(v)) return;" not in core
    assert "if (c === el || !isCarrySource(c, entry)) return;" not in core
    assert "movieKeyFor(c, c.currentSrc || c.src || '') !== entry.movieKey) return;" in core
    # The matcher itself is untouched: retireRestarted still retires only the real src.
    assert core.count("return c.__obedInstance === entry.src.objectId;") == 1


def test_wrong_instance_prefers_a_same_asset_candidate_that_is_not_src() -> None:
    core = variants.variant_core("wrong-instance")
    wrong = "const wrong = found.filter(function(c) { return !isCarrySource(c, entry); });"
    assert core.index(wrong) < core.index("if (wrong.length) return wrong[0];") < core.index("const reason = found.length === 0")


def test_fifo_reuse_takes_the_first_same_asset_candidate() -> None:
    core = variants.variant_core("fifo-reuse")
    assert core.index("if (found.length) return found[0];") < core.index("const reason = found.length === 0")


@pytest.mark.parametrize(("name", "anchor"), ANCHORS)
def test_a_core_without_an_anchor_raises_naming_variant_and_anchor(name: str, anchor: str) -> None:
    with pytest.raises(ValueError) as caught:
        variants.variant_core(name, PRESERVE_CORE_JS.replace(anchor, ""))
    assert name in str(caught.value) and anchor.strip() in str(caught.value)


@pytest.mark.parametrize(("name", "anchor"), ANCHORS)
def test_a_core_with_an_anchor_twice_raises(name: str, anchor: str) -> None:
    with pytest.raises(ValueError, match="2 times"):
        variants.variant_core(name, PRESERVE_CORE_JS + anchor)


def test_an_unknown_variant_raises() -> None:
    with pytest.raises(ValueError, match="unknown core variant"):
        variants.variant_core("lifo")


def _end(object_id: str) -> dict[str, Any]:
    return {"objectId": object_id, "rect": {"x": 0, "y": 0, "w": 10, "h": 10}}


RUNTIME = {
    "schema": 2,
    "movies": {"movie1": {"assetKeys": ["untitled.mov"]}, "movie2": {"assetKeys": ["b.mov"]}},
    "boundaries": [
        {"atScene": 2, "action": "retire", "movieKey": "movie1", "reason": "refused", "src": _end("A1")},
        {"atScene": 6, "action": "restart", "movieKey": "movie1", "src": _end("A2"), "dst": _end("A3")},
        {"atScene": 8, "action": "bridge", "movieKey": "movie1", "src": _end("A3"), "dst": _end("A4")},
        {"atScene": 8, "action": "pin", "movieKey": "movie2", "src": _end("B3"), "dst": _end("B4")},
        {"atScene": 10, "action": "restart", "movieKey": "movie1", "src": _end("A4")},
    ],
}


def _kept(stripped: dict[str, Any]) -> list[tuple[int, str, str]]:
    return [(b["atScene"], b["action"], b["movieKey"]) for b in stripped["boundaries"]]


def test_strip_drops_every_entry_of_the_action_without_a_scene() -> None:
    stripped = variants.strip_entries(RUNTIME, "restart")
    assert _kept(stripped) == [(2, "retire", "movie1"), (8, "bridge", "movie1"), (8, "pin", "movie2")]


def test_strip_at_a_scene_drops_only_that_entry() -> None:
    stripped = variants.strip_entries(RUNTIME, "restart", 6)
    assert _kept(stripped) == [(2, "retire", "movie1"), (8, "bridge", "movie1"), (8, "pin", "movie2"), (10, "restart", "movie1")]


@pytest.mark.parametrize("key", ["movie2", "B3", "b4"])
def test_strip_with_a_key_drops_only_the_entry_naming_it(key: str) -> None:
    stripped = variants.strip_entries(RUNTIME, "pin", 8, key)
    assert _kept(stripped) == [(2, "retire", "movie1"), (6, "restart", "movie1"), (8, "bridge", "movie1"), (10, "restart", "movie1")]


def test_strip_with_a_key_no_entry_names_raises() -> None:
    with pytest.raises(ValueError, match="no pin@8:movie1"):
        variants.strip_entries(RUNTIME, "pin", 8, "movie1")


def test_the_key_matches_movie_key_and_both_object_ids() -> None:
    assert variants.entry_keys(RUNTIME["boundaries"][2]) == {"movie1", "a3", "a4"}
    assert variants.entry_keys(RUNTIME["boundaries"][0]) == {"movie1", "a1"}


def test_strip_is_a_deep_copy_and_leaves_the_input_alone() -> None:
    before = copy.deepcopy(RUNTIME)
    stripped = variants.strip_entries(RUNTIME, "bridge", 8)
    stripped["movies"]["movie1"]["assetKeys"].append("x")
    assert RUNTIME == before


@pytest.mark.parametrize(("action", "scene"), [("pin", 2), ("bridge", 6), ("glReplay", 2)])
def test_strip_raises_when_nothing_matches(action: str, scene: int | None) -> None:
    with pytest.raises(ValueError, match="no "):
        variants.strip_entries(RUNTIME, action, scene)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bridge@8", ("bridge", 8, None)), ("retire", ("retire", None, None)), ("glReplay@2", ("glReplay", 2, None)),
        (" restart@6 ", ("restart", 6, None)), ("pin@4:movie2", ("pin", 4, "movie2")),
        ("pin@4:6BB39942-6C61-4763-839D-777C09E7E594", ("pin", 4, "6BB39942-6C61-4763-839D-777C09E7E594")),
    ],
)
def test_parse_strip(value: str, expected: tuple[str, int | None, str | None]) -> None:
    assert variants.parse_strip(value) == expected


@pytest.mark.parametrize("value", ["", "@8", "bridge@", "bridge@x", "bridge@8@9", "bri dge", "pin:movie2", "pin@4:", "pin@4:a b"])
def test_parse_strip_rejects_malformed(value: str) -> None:
    with pytest.raises(ValueError):
        variants.parse_strip(value)


@pytest.mark.parametrize(
    ("args", "label"),
    [(("bridge", 8, None), "strip:bridge@8"), (("pin", 4, "movie2"), "strip:pin@4:movie2"), (("retire", None, None), "strip:retire")],
)
def test_strip_label(args: tuple[str, int | None, str | None], label: str) -> None:
    assert variants.strip_label(*args) == label
