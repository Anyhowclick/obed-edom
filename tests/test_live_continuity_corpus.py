"""The negative corpus (continuity generalisation plan, S3 and OQ-8 (iii)): with no allowlist,
every deck that derives is installed, so each refusal code must still fire on a real export
shape. One synthetic export per code, made by mutating the P2 fixture tree in `tmp_path`, runs
through the product path (`live_host.derive_runtime`) and derives its named reason.

The clean base is P2 with slide 2's green square authored below the movie, which refuses
nothing; the `overlap` case is P2 itself. Per-move codes retire their own carry and leave every
other boundary alone; deck-wide codes (`R3`, `R5`) refuse the deck.

`R6` (`_chain_refusal`) is a `to_runtime` integrity check no well-formed export reaches:
`derive_plan` gives each outgoing instance at most one entry per boundary, `R5` keeps sources
unique across slides, every held instance is continued or ended at the next boundary, and `R11`
retires any carry into a slide whose own transition plans nothing. It is covered on hand-built
plans by `test_r6_an_empty_boundary_after_a_bridge_breaks_the_chain` and
`test_r6_an_instance_that_is_the_source_of_two_entries_is_refused` in
`tests/test_live_continuity.py`.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from obed_edom import live_continuity
from obed_edom.live_continuity import ContinuityPlan, Unsupported
from obed_edom.live_host import derive_runtime, not_carried
from tests.test_live_continuity import (
    P2_OBJECT_IDS,
    SLIDE1,
    SLIDE2,
    SLIDE3,
    SLIDE4,
    SLIDES,
    _add_build,
    _add_scaled_movie_above_the_bridge,
    _clone_second_instance_onto_slide2,
    _copy_fixture_tree,
    _each_leaf,
    _map_transitions,
    _move_green_square_below_the_movie,
    _move_slide2_movie_centre,
    _resolver,
    _rewrite_slide_json,
    _set_loop_mode,
    _set_movie_field,
    _set_opacity,
    _set_slide1_small_opacity,
    _slide1_centres,
    _with_object_id,
)

_CLEAN = (SLIDE2, _move_green_square_below_the_movie)
_BETWEEN_SLIDE1_INSTANCES = tuple(sum(axis) / 2 for axis in zip(*_slide1_centres()))
_BOTH_SLIDE1 = ("slide1", "slide1_small")


def _move_transition_to_the_first_event(data):
    transition = data["events"][-1]["effects"].pop(0)
    assert transition["type"] == "transition"
    data["events"][0]["effects"].append(transition)
    return data


def _tree(tmp_path: Path, mutations) -> Path:
    root = _copy_fixture_tree(tmp_path)
    for uuid, transform in mutations:
        _rewrite_slide_json(root, uuid, transform)
    return root


def _derive(root: Path) -> tuple[ContinuityPlan, dict] | Unsupported:
    return derive_runtime(root, SLIDES, resolver=_resolver)


def _carries(runtime: dict, skip: set[int]) -> list[tuple]:
    return [
        (e["atScene"], e["action"], e["src"]["objectId"], e.get("dst", {}).get("objectId"))
        for e in runtime["boundaries"]
        if e["atScene"] not in skip
    ]


PER_MOVE = [
    pytest.param("overlap", [], 0, ("slide1",), "later-authored artwork overlaps the carried 'untitled.mov'", (), id="overlap"),
    pytest.param(
        "R1", [_CLEAN, (SLIDE2, _move_slide2_movie_centre(*_BETWEEN_SLIDE1_INSTANCES))], 0, _BOTH_SLIDE1,
        "(margin 16 px)", (), id="R1",
    ),
    pytest.param("R1b", [_CLEAN, (SLIDE1, _set_slide1_small_opacity(0.5))], 0, _BOTH_SLIDE1, "differ in opacity", (), id="R1b"),
    pytest.param(
        "R2", [_CLEAN, (SLIDE4, _add_build("buildIn", "apple:dissolve", P2_OBJECT_IDS["slide4"]))], 2, ("slide3",),
        "builds in or out at player index 2 -> 3", (), id="R2",
    ),
    pytest.param(
        "R4", [_CLEAN, (SLIDE3, _set_loop_mode((P2_OBJECT_IDS["slide3"],), "looping"))], 2, ("slide3",),
        "loops on one side of player index 2 -> 3 only", (), id="R4",
    ),
    pytest.param(
        "R7", [_CLEAN, (SLIDE4, _set_movie_field(P2_OBJECT_IDS["slide4"], "isStreaming", True))], 2, ("slide3",),
        "is a web movie, which the player draws without a <video>", (), id="R7",
    ),
    pytest.param(
        "R8", [_CLEAN, (SLIDE4, _set_movie_field(P2_OBJECT_IDS["slide4"], "endTime", 40.0))], 2, ("slide3",),
        "is trimmed differently on each side of player index 2 -> 3", (), id="R8",
    ),
    pytest.param(
        "R9", [_CLEAN, (SLIDE4, _set_opacity(P2_OBJECT_IDS["slide4"], 0.5))], 2, ("slide3",),
        "is not fully opaque on the destination slide", (), id="R9",
    ),
    pytest.param(
        "R10", [_CLEAN, (SLIDE3, _each_leaf(lambda leaf: leaf.__setitem__("timingFunction", "Linear")))], 2, ("slide3",),
        "does not move with the bridge's eased timing", (), id="R10",
    ),
    pytest.param(
        "R11", [_CLEAN, (SLIDE2, lambda data: _map_transitions(data, lambda _name: "apple:push"))], 0, ("slide1",),
        "the next transition 'apple:push' is unmeasured", (1,), id="R11-unmeasured-outgoing-transition",
    ),
    pytest.param(
        "R11", [_CLEAN, (SLIDE4, _add_scaled_movie_above_the_bridge)], 2, ("slide3",),
        "an unmeasured movie 'other.mov' is drawn above the carried 'untitled.mov'", (), id="R11-unmeasured-movie-above",
    ),
]

DECK_WIDE = [
    pytest.param("R3", (SLIDE1, _move_transition_to_the_first_event), id="R3"),
    pytest.param(
        "R5",
        (SLIDE2, lambda data: _with_object_id(P2_OBJECT_IDS["slide1_small"], _clone_second_instance_onto_slide2(data))),
        id="R5",
    ),
]


@pytest.mark.parametrize("code, mutations, boundary, refused, fragment, silenced", PER_MOVE)
def test_a_per_move_refusal_retires_only_its_own_carry(code, mutations, boundary, refused, fragment, silenced, tmp_path):
    """The deck installs (a runtime, not `Unsupported`); at the refused boundary each named source
    instance becomes a `retire` with `reason: "refused"` and nothing there is carried; the plan's
    refusal records and the operator's `notCarried` lines name exactly those instances, the code
    and the reason; every other boundary carries what the clean base carries. A `silenced`
    boundary is one an unmeasured transition leaves without entries at all."""
    tree = _tree(tmp_path, mutations)
    if code == "overlap":
        events = json.loads((tree / "assets" / SLIDE2 / f"{SLIDE2}.json").read_text())["events"]
        assert events[0]["automaticPlay"] is False, "overlap must stay on a click-driven destination"
    base = _derive(_tree(tmp_path, [_CLEAN]))
    derived = _derive(tree)
    assert not isinstance(base, Unsupported), base
    assert not isinstance(derived, Unsupported), derived
    (_, base_runtime), (plan, runtime) = base, derived
    assert base[0].refusals == ()

    object_ids = sorted(P2_OBJECT_IDS[key] for key in refused)
    scene = plan.scene_index_by_player[boundary + 1]
    at_scene = [e for e in runtime["boundaries"] if e["atScene"] == scene]
    assert sorted(e["src"]["objectId"] for e in at_scene) == object_ids
    assert all(e["action"] == "retire" and e["reason"] == "refused" for e in at_scene), at_scene

    assert sorted((r["code"], r["fromPlayer"], r["objectId"]) for r in plan.refusals) == [
        (code, boundary, object_id) for object_id in object_ids
    ]
    assert all(fragment in r["reason"] for r in plan.refusals), plan.refusals
    lines = not_carried(plan, SLIDES)
    assert sorted((e["code"], e["asset"], e["fromSlide"], e["toSlide"], e["objectId"]) for e in lines) == [
        (code, "untitled.mov", boundary + 1, boundary + 2, object_id) for object_id in object_ids
    ]

    quiet = {plan.scene_index_by_player[index + 1] for index in silenced}
    assert not [e for e in runtime["boundaries"] if e["atScene"] in quiet]
    assert _carries(runtime, {scene, *quiet}) == _carries(base_runtime, {scene, *quiet})


@pytest.mark.parametrize("code, mutation", DECK_WIDE)
def test_a_deck_wide_refusal_refuses_the_deck(code, mutation, tmp_path):
    result = _derive(_tree(tmp_path, [_CLEAN, mutation]))
    assert isinstance(result, Unsupported)
    assert result.reason.startswith(f"{code}: "), result.reason


def test_the_corpus_covers_every_refusal_code_the_product_can_emit():
    """A new code literal in `live_continuity` without a corpus entry fails here. `R6` is
    unreachable from an export (module docstring)."""
    emitted = set(re.findall(r"\"(overlap|R\d+b?)[\":]", inspect.getsource(live_continuity)))
    covered = {param.values[0] for param in PER_MOVE + DECK_WIDE} | {"R6"}
    assert emitted == covered
