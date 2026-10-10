from __future__ import annotations

import copy
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from obed_edom.fixture_paths import fixture
from obed_edom.live_continuity import (
    ContinuityPlan,
    MovieContinuity,
    Rect,
    Unsupported,
    _check_effect_encoding,
    _IDENTITY_SUBLAYER_TRANSFORM,
    _Refuse,
    codec_report,
    derive_plan,
    effect_opacity_overrides,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
REAL_EXPORT_ROOT = fixture("p2-recovery") / "html-adversarial" / "html-unmodified"

REAL_PLAYER_ROOT = fixture("p2-recovery") / "html-adversarial" / "html-player"

SLIDE1 = "08C861A1-CB39-4832-B189-6DF95B7F3396"
SLIDE2 = "0C652BEB-F445-48CF-BFD0-4194C6B7A438"
SLIDE3 = "D4D95253-4C37-40CF-A4A4-62D8DE24EF2A"
SLIDE4 = "7A851F4D-4648-4545-A491-58838A7CD843"

SLIDES = [
    {"playerIndex": 0, "originalOrdinal": 1, "exportedUuid": SLIDE1, "skipped": False},
    {"playerIndex": 1, "originalOrdinal": 2, "exportedUuid": SLIDE2, "skipped": False},
    {"playerIndex": 2, "originalOrdinal": 3, "exportedUuid": SLIDE3, "skipped": False},
    {"playerIndex": 3, "originalOrdinal": 4, "exportedUuid": SLIDE4, "skipped": False},
]

# The green square is slide 2's draw slot 6; the movie is slot 5.
SLIDE2_GREEN_SLOT = 6
SLIDE2_MOVIE_SLOT = 5


def _resolver(root: Path, relative: str) -> Path:
    """Minimal traversal-safe resolver used by these tests (mirrors safe_export_file's checks
    without requiring the export to sit under the preview cache)."""
    parts = Path(relative).parts
    if not relative or relative.startswith("/") or "\\" in relative:
        raise ValueError("invalid path")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("path traversal rejected")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if resolved_root not in candidate.parents and candidate != resolved_root:
        raise ValueError("outside root")
    if not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _unchecked_resolver(root: Path, relative: str) -> Path:
    return root / relative


def _plan(root: Path = FIXTURE_ROOT, slides: list[dict] = SLIDES) -> ContinuityPlan | Unsupported:
    return derive_plan(root, slides, resolver=_resolver)


def _rect(x, y, w, h):
    return {"x": pytest.approx(x, abs=0.05), "y": pytest.approx(y, abs=0.05), "w": pytest.approx(w, abs=0.05), "h": pytest.approx(h, abs=0.05)}


def _boundary(plan: ContinuityPlan, from_index: int) -> dict:
    for b in plan.boundaries:
        if b.from_player_index == from_index:
            return b.as_dict()
    raise AssertionError(f"no boundary from player index {from_index}")


def test_fixture_present():
    assert (FIXTURE_ROOT / "assets" / "header.json").is_file()
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        assert (FIXTURE_ROOT / "assets" / uuid / f"{uuid}.json").is_file()


def test_canvas_and_scene_boundaries():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.canvas == {"width": 1920, "height": 1080}
    assert plan.scene_index_by_player == {0: 0, 1: 2, 2: 6, 3: 8}


@pytest.mark.parametrize(
    "from_index, boundary_fields, movie_fields",
    [
        # Slide 1 authors TWO Untitled.mov instances (the second, non-continuing one at ~(1076, 876),
        # the plan's noted 'movie2' drift). Only one has an identical-geometry counterpart on slide
        # 2, so ownership is not ambiguous: the narrow rule is 'refuse only when more than one
        # instance has a geometry-equal match on the far side', not 'whenever more than one
        # instance of an asset exists'. This is the fixture P2 qualified, so it must still plan.
        pytest.param(
            0, {"toPlayerIndex": 1},
            {"action": "pin", "srcRect": _rect(109.35, 795.04, 951.54, 267.62), "dstRect": _rect(109.35, 795.04, 951.54, 267.62)},
            id="1-to-2-pins-the-static-movie-of-two-same-asset-instances",
        ),
        pytest.param(1, {"toPlayerIndex": 2}, {"action": "restart"}, id="2-to-3-restarts-across-the-dissolve"),
        # WA0125 does not appear on slide 4: it must not be treated as continuing. The authored
        # y=797.10 is the DATA value (see test_slide3_authored_y_differs_from_p2s_measured_constant_within_tolerance).
        pytest.param(
            2, {"toPlayerIndex": 3, "durationSeconds": 1.5},
            {"action": "bridge", "srcRect": _rect(197.98, 797.10, 951.54, 267.62), "dstRect": _rect(326.75, 708.52, 1266.49, 356.20)},
            id="3-to-4-bridges-the-moving-scaling-movie-at-authored-y-797.10",
        ),
        pytest.param(3, {"toPlayerIndex": None}, {"action": "restart", "dstRect": None}, id="4-to-end-restarts-with-no-destination"),
    ],
)
def test_fixture_boundary_carries_only_untitled_mov(from_index, boundary_fields, movie_fields):
    boundary = _boundary(_plan(), from_index)
    assert {key: boundary[key] for key in boundary_fields} == boundary_fields
    assert [m["asset"] for m in boundary["movies"]] == ["untitled.mov"]
    assert {key: boundary["movies"][0][key] for key in movie_fields} == movie_fields


def test_slide3_authored_y_differs_from_p2s_measured_constant_within_tolerance():
    """Known discrepancy (plan section 2): a previous analysis derived y=797 for slide 3's
    movie while P2's screen-measured MOVIE constant used 795 (authored notes: 794.6). The
    export data says y=797.10 (the 3-to-4 case of test_fixture_boundary_carries_only_untitled_mov);
    P2's 795 is off by ~2.1px, comfortably inside the probe's stated 10px per-axis tolerance,
    consistent with it being a screen-measured rather than authored value. This test pins the
    DATA value; it must not be relaxed to force-fit 795.
    """
    src = next(m for m in _boundary(_plan(), 2)["movies"] if m["asset"] == "untitled.mov")["srcRect"]
    assert src["y"] == pytest.approx(797.10, abs=0.05)
    p2_measured_y = 795
    assert abs(src["y"] - p2_measured_y) < 10


def test_r5_an_object_id_repeated_across_slides_refuses_the_deck():
    """Slide 2 gains a copy of slide 1's small instance, objectID and all: the runtime keys every
    carry on `objectID`, so a repeated id cannot be expressed (plan R5)."""
    tmp = _mutate_slide(
        SLIDE2, lambda data: _with_object_id(P2_OBJECT_IDS["slide1_small"], _clone_second_instance_onto_slide2(data))
    )
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert plan == Unsupported(
        f"R5: movie object {P2_OBJECT_IDS['slide1_small']} appears on player index 0 and 1"
    )


def _with_object_id(object_id: str, data):
    """Name the clone and give it a draw slot, behind everything, on slide 2's first event."""
    data["events"][-1]["effects"][0]["effects"][-1]["objectID"] = object_id
    _draw_slots(data, 0).insert(0, _authored_slot(*SLIDE1_SMALL, object_id=object_id))
    return data


def test_a_second_destination_instance_pairs_by_centre_distance():
    """With a fresh objectID the same clone is not ambiguous: each slide-1 instance pairs with its
    geometry-equal twin by minimum total centre distance (plan section 2.2)."""
    tmp = _mutate_slide(SLIDE2, lambda data: _with_object_id("CLONE", _clone_second_instance_onto_slide2(data)))
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    pairs = {(m.src_object_id, m.dst_object_id, m.action) for m in plan.boundaries[0].movies}
    assert pairs == {
        (P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide2"], "pin"),
        (P2_OBJECT_IDS["slide1_small"], "CLONE", "pin"),
    }


def _move_slide2_movie_centre(x: float, y: float):
    def move(node):
        node["baseLayer"]["initialState"]["position"] = {"pointX": x, "pointY": y}

    return lambda data: _map_movie_nodes(data, move)


def _slide1_centres() -> tuple[tuple[float, float], tuple[float, float]]:
    return (
        (SLIDE1_BIG[0] + SLIDE1_BIG[2] / 2, SLIDE1_BIG[1] + SLIDE1_BIG[3] / 2),
        (SLIDE1_SMALL[0] + SLIDE1_SMALL[2] / 2, SLIDE1_SMALL[1] + SLIDE1_SMALL[3] / 2),
    )


@pytest.mark.parametrize("offset, refused", [(0.0, True), (7.9, True), (8.1, False)])
def test_r1_a_runner_up_pairing_within_16_px_refuses_the_boundary(offset, refused):
    """Slide 2's one instance sits `offset` px from the midpoint of slide 1's two centres, along
    the line between them, so the two assignments differ by 2 x offset."""
    (bx, by), (sx, sy) = _slide1_centres()
    length = math.dist((bx, by), (sx, sy))
    ux, uy = (sx - bx) / length, (sy - by) / length
    cx, cy = (bx + sx) / 2 - ux * offset, (by + sy) / 2 - uy * offset
    plan = _plan(_mutate_slide(SLIDE2, _move_slide2_movie_centre(cx, cy)))
    assert isinstance(plan, ContinuityPlan)
    movies = plan.boundaries[0].movies
    if refused:
        assert [(m.action, m.code, m.src_object_id, m.dst_object_id) for m in movies] == [
            ("retire", "R1", P2_OBJECT_IDS["slide1"], None),
            ("retire", "R1", P2_OBJECT_IDS["slide1_small"], None),
        ]
        assert "(margin 16 px)" in movies[0].refusal
        assert [r["code"] for r in plan.refusals] == ["R1", "R1"]
    else:
        assert [(m.action, m.src_object_id) for m in movies] == [("bridge", P2_OBJECT_IDS["slide1"])]


def _set_slide1_small_opacity(value: float):
    def apply(node):
        if node.get("objectID") == P2_OBJECT_IDS["slide1_small"]:
            node["baseLayer"]["initialState"]["opacity"] = value

    return lambda data: _map_movie_nodes(data, apply)


def test_r1b_candidates_that_differ_in_opacity_refuse_the_boundary():
    """Keynote pairs by opacity before distance (F3), so a distance-only pairing is unsafe."""
    plan = _plan(_mutate_slide(SLIDE1, _set_slide1_small_opacity(0.5)))
    assert isinstance(plan, ContinuityPlan)
    movies = plan.boundaries[0].movies
    assert [(m.action, m.code) for m in movies] == [("retire", "R1b"), ("retire", "R1b")]
    assert "differ in opacity" in movies[0].refusal


def test_r1b_does_not_apply_when_there_is_no_choice():
    """One instance on each side: no pairing preference can change the outcome."""
    plan = _plan(_mutate_slide(SLIDE2, _set_slide1_small_opacity(0.5)))
    assert isinstance(plan, ContinuityPlan)
    plan_opaque = _plan()
    assert plan.boundaries[1].movies == plan_opaque.boundaries[1].movies


@pytest.mark.parametrize(
    "relative, text, reason",
    [
        pytest.param("assets/header.json", "{not json", "unreadable export header: ", id="header"),
        pytest.param(f"assets/{SLIDE1}/{SLIDE1}.json", "not json at all", "unreadable slide export for player index 0: ", id="slide-json"),
    ],
)
def test_refuses_an_unreadable_export_file(relative, text, reason):
    tmp = _copy_fixture_tree()
    (tmp / relative).write_text(text)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert plan.reason.startswith(reason)


def _add_wa0125_to_slide4(data):
    """Slide 3 already carries a WA0125 instance; add a matching one on slide 4 so it also
    "continues" (with different geometry) across the 3->4 magic move alongside Untitled.mov."""
    events = copy.deepcopy(data["events"])
    movie_nodes = _find_movie_nodes(events)
    assert movie_nodes
    clone = copy.deepcopy(movie_nodes[0])
    clone["movie"] = {
        "startTime": 0,
        "volume": 1,
        "endTime": 45.1,
        "isStreaming": False,
        "isAudioOnly": False,
        "asset": "VID-20250608-WA0125.mp4-0.0000-45.1381",
    }
    state = clone["baseLayer"]["initialState"]
    state["position"]["pointX"] += 80
    state["position"]["pointY"] += 80
    clone_id = "CLONE-WA0125"
    events[0]["effects"][0]["effects"] = events[0]["effects"][0].get("effects", []) + [
        {
            "objectID": clone_id, "movie": clone["movie"],
            "baseLayer": clone["baseLayer"], "effects": [],
        }
    ]
    data = {**data, "events": events}
    # the overlap rule reads the destination slide's draw order, so the clone needs a slot
    # of its own; put it BELOW the existing movie so it adds no overlap of its own.
    rect = (state["position"]["pointX"] - state["width"] / 2,
            state["position"]["pointY"] - state["height"] / 2, state["width"], state["height"])
    _draw_slots(data, 0).insert(1, _authored_slot(*rect, object_id=clone_id))
    data["assets"] = {
        **data["assets"],
        "VID-20250608-WA0125.mp4-0.0000-45.1381": {
            "type": "video",
            "url": {"web": "assets/VID-20250608-WA0125.mp4-0.0000-45.1381.mp4"},
        },
    }
    return data


def _drop_every_movie_slot(data):
    data = _move_green_square_below_the_movie(data)
    movie_id = _slot_object(data, 0, SLIDE2_GREEN_SLOT)["objectID"]
    for index in _events_drawing(data, movie_id):
        del _draw_slots(data, index)[SLIDE2_GREEN_SLOT]
    return data


def _strip_base_layer(data):
    for event in data["events"]:
        event.pop("baseLayer")
    return data


def _tamper_slot_layers(slot_index: int, layers):
    def tamper(data):
        slot = _draw_slots(data, 0)[slot_index]
        slot["layers"] = layers(slot["layers"])
        return data

    return tamper


_MOVIE_LAYER_TRANSFORMED = "has a rotated, transformed, or off-center anchor"


@pytest.mark.parametrize(
    "uuid, transform, reason",
    [
        pytest.param(SLIDE1, lambda data: {**data, "events": []}, "slide at player index 0 has no events", id="no-events"),
        pytest.param(
            SLIDE1, lambda data: _map_transitions(data, lambda _name: "apple:cube"),
            "unsupported transition 'apple:cube' at player index 0 -> 1", id="unknown-transition-on-a-magic-move",
        ),
        pytest.param(
            SLIDE1, lambda data: _map_movie_nodes(data, lambda node: node["baseLayer"]["initialState"].__setitem__("rotation", 5)),
            f"movie layer on slide {SLIDE1} {_MOVIE_LAYER_TRANSFORMED}", id="rotated-movie-layer",
        ),
        pytest.param(
            SLIDE1,
            lambda data: _map_movie_nodes(
                data, lambda node: node["baseLayer"]["initialState"].__setitem__("affineTransform", [1, 0.2, 0, 1, 0, 0])
            ),
            f"movie layer on slide {SLIDE1} {_MOVIE_LAYER_TRANSFORMED}", id="non-identity-affine-transform",
        ),
        pytest.param(
            SLIDE4, _add_wa0125_to_slide4, "more than one movie changes geometry at player index 2 -> 3",
            id="two-geometry-changing-movies-on-one-boundary",
        ),
        # The draw order (see the overlap section below) must be readable for every movie.
        pytest.param(
            SLIDE2, _drop_every_movie_slot, f"movie 'untitled.mov' has no draw slot on slide {SLIDE2}",
            id="movie-slot-absent-in-every-event",
        ),
        pytest.param(
            SLIDE2, _tamper_slot_layers(SLIDE2_GREEN_SLOT, lambda layers: layers * 2),
            f"unrecognised slide layer shape on slide {SLIDE2} (draw slot 6)", id="slot-above-the-movie-with-two-children",
        ),
        pytest.param(
            SLIDE2, _tamper_slot_layers(SLIDE2_MOVIE_SLOT, lambda _layers: "not a list"),
            f"unrecognised slide layer shape on slide {SLIDE2} (draw slot 5)", id="non-list-layers-on-a-draw-slot",
        ),
        pytest.param(
            SLIDE2, _strip_base_layer, f"slide {SLIDE2} declares no readable draw order", id="no-draw-order-at-all",
        ),
        # Without an objectID the movie cannot be located in the draw order at all, so its
        # z-position is unknown and nothing may be carried across the boundary.
        pytest.param(
            SLIDE2, lambda data: _map_movie_nodes(data, lambda node: node.pop("objectID")),
            f"movie on slide {SLIDE2} has no object id", id="movie-node-without-an-object-id",
        ),
    ],
)
def test_refuses_the_deck(uuid, transform, reason):
    assert _plan(_mutate_slide(uuid, transform)) == Unsupported(reason)


@pytest.mark.parametrize("ancestor_change", [None, "position", "rotation", "animation"])
def test_refuses_video_below_an_intermediate_layer(ancestor_change):
    def nest_video(node):
        base = node["baseLayer"]
        for index, layer in enumerate(base["layers"]):
            if not layer.get("isVideoLayer"):
                continue
            ancestor = {
                "initialState": copy.deepcopy(base["initialState"]),
                "layers": [layer],
                "animations": [],
            }
            if ancestor_change == "position":
                ancestor["initialState"]["position"]["pointX"] += 80
            elif ancestor_change == "rotation":
                ancestor["initialState"]["rotation"] = 30
            elif ancestor_change == "animation":
                ancestor["animations"] = [{"property": "position", "duration": 1.5}]
            base["layers"][index] = ancestor

    tmp = _mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, nest_video))
    plan = _plan(tmp)
    assert isinstance(plan, Unsupported)
    # the export's `animations` lists are always empty, so an animation entry is an object the
    # mask vocabulary has never measured and is refused before the nesting is even reached.
    expected = "possible mask" if ancestor_change == "animation" else "not a direct child"
    assert expected in plan.reason


@pytest.mark.parametrize(
    "extra, refusal",
    [
        pytest.param({"playerIndex": 4, "originalOrdinal": 5, "exportedUuid": "does-not-exist", "skipped": True}, None, id="skipped-slide"),
        pytest.param({"playerIndex": 9, "skipped": True}, None, id="skipped-slide-missing-uuid"),
        pytest.param(
            {"playerIndex": 9, "skipped": False}, "a non-skipped slide is missing playerIndex or exportedUuid",
            id="non-skipped-slide-missing-uuid",
        ),
    ],
)
def test_a_skipped_slide_is_ignored_and_does_not_shift_scene_indices(extra, refusal):
    plan = derive_plan(FIXTURE_ROOT, [*SLIDES, extra], resolver=_resolver)
    if refusal is not None:
        assert plan == Unsupported(refusal)
        return
    assert isinstance(plan, ContinuityPlan)
    assert plan.scene_index_by_player == {0: 0, 1: 2, 2: 6, 3: 8}


def test_path_traversal_is_impossible():
    slides = copy.deepcopy(SLIDES)
    slides[0]["exportedUuid"] = "../../../../etc"
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unreadable slide export" in plan.reason


def test_plan_and_slide_instances_round_trip_through_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    restored = json.loads(plan.to_json())
    assert restored == plan.as_dict()
    assert restored["canvas"] == {"width": 1920, "height": 1080}
    assert restored["sceneIndexByPlayer"]["2"] == 6
    assert restored["slideInstances"]["0"]["untitled.mov"] == [
        _rect(*SLIDE1_BIG),
        _rect(*SLIDE1_SMALL),
    ]
    assert list(restored["slideInstances"]) == ["0", "1", "2", "3"]


@pytest.mark.skipif(not REAL_EXPORT_ROOT.is_dir(), reason="real P2 export not available")
def test_real_export_matches_trimmed_fixture_plan():
    real_plan = derive_plan(REAL_EXPORT_ROOT, SLIDES, resolver=_resolver)
    fixture_plan = _plan()
    assert isinstance(real_plan, ContinuityPlan)
    assert isinstance(fixture_plan, ContinuityPlan)
    assert real_plan.as_dict() == fixture_plan.as_dict()


# P2's injected fixture plan (scripts/p2_recovery_html_adversarial.py MOVIE_ROI /
# SLIDE3_MIN_HASH / SLIDE4_MIN_HASH / SLIDE4_MOVIE_RECT), the equivalence target
# for `to_runtime()`. Scenes exact; rects within 3px (the documented slide-3
# y=797.1 vs P2's screen-measured 795 is a known ~2.1px discrepancy).
P2_MOVIE1_FOOTPRINT = {"x": 109, "y": 795, "w": 952, "h": 268}
P2_SLIDE3_MIN_HASH = 6
P2_SLIDE3_MOVIE_RECT = {"x": 198, "y": 797, "w": 952, "h": 268}
P2_SLIDE4_MIN_HASH = 8
P2_SLIDE4_MOVIE_RECT = {"x": 327, "y": 709, "w": 1266, "h": 356}
# The 1->2 Magic Move destination: refused (slide 2 draws the green square OVER the carried
# movie), so the runtime is told to hand the movie back to the player at that scene.
P2_SLIDE2_MIN_HASH = 2

# `derive_plan` on the fixture must produce exactly the schema-2 contract example (generalisation
# plan section 2.1), which the core and P2-injection streams test against too.
RUNTIME_V2_EXAMPLES = json.loads((FIXTURE_ROOT / "runtime_v2_examples.json").read_text())
EXPECTED_RUNTIME_PLAN = RUNTIME_V2_EXAMPLES["p2_off"]
EXPECTED_PLAN_SHA256 = "283f5eecd18c3412172e28a40bc716c69173a7c72bcd37379dcd3d7d6a96dd4e"
P2_OBJECT_IDS = {
    "slide1": "6BB39942-6C61-4763-839D-777C09E7E594",
    "slide1_small": "CBACAF27-B918-47C2-AB45-3ED71B6B394B",
    "slide2": "F9AFED1B-E2D7-47D4-942E-14992C808383",
    "slide3": "98D59E27-7807-477D-BEFB-27EB1CF1D185",
    "slide3_wa0125": "2FE5195A-F8CF-459A-8E20-B6DF91C0047A",
    "slide4": "E4728E7D-2032-4D7F-83D6-8BE0EFB7B7BC",
}


def _rect_close(a: dict, b: dict, tol: float = 3.0) -> bool:
    return all(abs(a[k] - b[k]) <= tol for k in ("x", "y", "w", "h"))


def test_to_runtime_matches_p2_injected_plan():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert runtime["schema"] == 2

    # WA0125 and slide 1's small instance never continue, so no entry names them and the
    # movie table has one movie; its footprint is its first planned instance's rect.
    assert set(runtime["movies"]) == {"movie1"}
    movie1 = runtime["movies"]["movie1"]
    assert movie1["assetKeys"] == ["untitled.mov"]
    assert _rect_close(movie1["footprint"], P2_MOVIE1_FOOTPRINT)

    boundaries = {b["atScene"]: b for b in runtime["boundaries"]}
    assert set(boundaries) == {P2_SLIDE2_MIN_HASH, P2_SLIDE3_MIN_HASH, P2_SLIDE4_MIN_HASH}
    assert all(b["movieKey"] == "movie1" for b in runtime["boundaries"])
    retire = boundaries[P2_SLIDE2_MIN_HASH]
    assert (retire["action"], retire["reason"]) == ("retire", "refused")
    assert retire["src"]["objectId"] == P2_OBJECT_IDS["slide1"]
    restart = boundaries[P2_SLIDE3_MIN_HASH]
    assert restart["action"] == "restart"
    assert (restart["src"]["objectId"], restart["dst"]["objectId"]) == (P2_OBJECT_IDS["slide2"], P2_OBJECT_IDS["slide3"])
    bridge = boundaries[P2_SLIDE4_MIN_HASH]
    assert bridge["action"] == "bridge"
    assert bridge["src"] == {"objectId": P2_OBJECT_IDS["slide3"], "rect": P2_SLIDE3_MOVIE_RECT}
    assert bridge["dst"]["objectId"] == P2_OBJECT_IDS["slide4"]
    assert bridge["durationSeconds"] == 1.5
    assert bridge["loop"] is False
    assert _rect_close(bridge["dst"]["rect"], P2_SLIDE4_MOVIE_RECT)


def test_to_runtime_refuses_when_no_boundaries():
    plan = ContinuityPlan(canvas={"width": 1, "height": 1}, scene_index_by_player={0: 0}, slide_rects={}, boundaries=())
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)


@pytest.mark.parametrize(
    "field, end",
    [("src_rect", "source"), ("src_object_id", "source"), ("dst_rect", "destination"), ("dst_object_id", "destination")],
)
def test_to_runtime_refuses_bridge_without_an_instance(field, end):
    plan = _plan()
    bridge = replace(
        plan.boundaries[2],
        movies=tuple(replace(movie, **{field: None}) for movie in plan.boundaries[2].movies),
    )
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert f"does not name its {end} instance" in result.reason


@pytest.mark.parametrize("duration", [None, 0, -1, True, "1.5", float("nan"), float("inf")])
def test_to_runtime_refuses_bridge_without_positive_export_duration(duration):
    def change_duration(data):
        for event in data["events"]:
            for effect in event["effects"]:
                if effect.get("type") == "transition":
                    if duration is None:
                        effect.pop("duration")
                    else:
                        effect["duration"] = duration
        return data

    plan = _plan(_mutate_slide(SLIDE3, change_duration))
    assert isinstance(plan, ContinuityPlan)
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)
    assert "no finite positive export duration" in result.reason


def test_to_runtime_refuses_unqualified_export_duration():
    plan = _plan()
    bridge = replace(plan.boundaries[2], transition_duration=2.5)
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "not yet qualified" in result.reason


def _signed(monkeypatch, plan: ContinuityPlan) -> dict:
    """The runtime `to_runtime()` signed, whether or not the allowlist then withholds it."""
    from obed_edom import live_continuity

    signed: list[dict] = []
    real = live_continuity.plan_signature
    monkeypatch.setattr(live_continuity, "plan_signature", lambda runtime: (signed.append(runtime), real(runtime))[1])
    plan.to_runtime()
    monkeypatch.setattr(live_continuity, "plan_signature", real)
    assert len(signed) == 1
    return signed[0]


def test_r6_an_empty_boundary_after_a_bridge_breaks_the_chain():
    """R6: the bridged slide-4 instance is carried, so the boundary out of slide 4 must continue or
    end it; a deck that goes on to a slide with no entry for it cannot be expressed."""
    plan = _plan()
    empty = replace(plan.boundaries[3], to_player_index=4, movies=())
    result = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], empty),
    ).to_runtime()
    assert result == Unsupported(
        f"R6: the bridge at scene 8 carries {P2_OBJECT_IDS['slide4']}, which no entry at scene 10 continues or ends"
    )


def test_r6_the_last_slide_needs_no_entry_for_what_it_carries():
    plan = _plan()
    assert plan.boundaries[3].to_player_index is None
    assert plan.to_runtime() == EXPECTED_RUNTIME_PLAN


def test_r6_an_instance_that_is_the_source_of_two_entries_is_refused():
    plan = _plan()
    bridge = plan.boundaries[2]
    doubled = replace(bridge, movies=(*bridge.movies, replace(bridge.movies[0], action="restart")))
    result = replace(plan, boundaries=(*plan.boundaries[:2], doubled, plan.boundaries[3])).to_runtime()
    assert result == Unsupported(f"R6: instance {P2_OBJECT_IDS['slide3']} is the source of more than one entry")


def test_a_chain_of_carries_after_a_restart_and_a_bridge_is_expressible(monkeypatch):
    """Today's one-bridge / nothing-after-a-bridge limits are gone: the P2 bridge followed by a
    pin onto a fifth slide signs as a chain."""
    plan = _plan()
    pin = MovieContinuity(
        "untitled.mov", "pin", plan.boundaries[2].movies[0].dst_rect, plan.boundaries[2].movies[0].dst_rect,
        src_object_id=P2_OBJECT_IDS["slide4"], dst_object_id="SLIDE5-MOVIE",
    )
    extended = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], replace(plan.boundaries[3], to_player_index=4, movies=(pin,))),
    )
    runtime = _signed(monkeypatch, extended)
    assert [(b["atScene"], b["action"]) for b in runtime["boundaries"]] == [
        (2, "retire"), (6, "restart"), (8, "bridge"), (10, "pin"),
    ]
    assert runtime["boundaries"][-1]["src"]["objectId"] == runtime["boundaries"][-2]["dst"]["objectId"]


# --- fixture mutation helpers -------------------------------------------------------------


def _copy_fixture_tree(tmp_path: Path | None = None) -> Path:
    import shutil
    import tempfile

    dest = Path(tempfile.mkdtemp(prefix="live-continuity-fixture-"))
    shutil.copytree(FIXTURE_ROOT, dest, dirs_exist_ok=True)
    return dest


def _rewrite_slide_json(root: Path, uuid: str, transform) -> None:
    path = root / "assets" / uuid / f"{uuid}.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps(transform(data)))


def _mutate_slide(uuid: str, transform) -> Path:
    tmp = _copy_fixture_tree()
    _rewrite_slide_json(tmp, uuid, transform)
    return tmp


def _find_movie_nodes(obj):
    found = []
    if isinstance(obj, dict):
        if "movie" in obj and "baseLayer" in obj:
            found.append(obj)
        for value in obj.values():
            found.extend(_find_movie_nodes(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_movie_nodes(item))
    return found


def _map_movie_nodes(data, fn):
    events = copy.deepcopy(data["events"])
    for node in _find_movie_nodes(events):
        fn(node)
    return {**data, "events": events}


def _map_transitions(data, rename):
    events = copy.deepcopy(data["events"])

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "transition" and "name" in obj:
                obj["name"] = rename(obj["name"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(events)
    return {**data, "events": events}


def _draw_slots(data, event_index: int) -> list:
    """The destination slide's back-to-front draw order for one event: a flat list of wrapper
    slots, each holding exactly one object node (see plan section 0)."""
    return data["events"][event_index]["baseLayer"]["layers"]


def _slot_object(data, event_index: int, slot_index: int) -> dict:
    return _draw_slots(data, event_index)[slot_index]["layers"][0]


def _slot_rect(node: dict) -> tuple[float, float, float, float]:
    state = node["initialState"]
    return (
        state["position"]["pointX"] - state["width"] / 2,
        state["position"]["pointY"] - state["height"] / 2,
        state["width"],
        state["height"],
    )


def _authored_slot(x, y, w, h, object_id: str | None = None) -> dict:
    node: dict = {}
    if object_id is not None:
        node["objectID"] = object_id
    node["initialState"] = {
        "position": {"pointX": x + w / 2, "pointY": y + h / 2}, "width": w, "height": h,
    }
    return {"layers": [node]}


def _events_drawing(data, object_id: str) -> list[int]:
    """Indices of the events whose draw order contains `object_id` -- slide 2's flattened
    transition event (a single canvas-sized slot) is not one of them."""
    return [
        index
        for index, _event in enumerate(data["events"])
        if any(
            slot["layers"][0].get("objectID") == object_id
            for slot in _draw_slots(data, index)
            if len(slot["layers"]) == 1
        )
    ]


def _clone_second_instance_onto_slide2(data):
    """Give slide 2 the same non-continuing 'movie2' rect that slide 1 authors, in addition
    to its real continuing instance, so two geometry-equal pin pairs exist and pinning
    ownership becomes genuinely ambiguous."""
    fixture_slide1 = json.loads((FIXTURE_ROOT / "assets" / SLIDE1 / f"{SLIDE1}.json").read_text())
    stray = copy.deepcopy(_find_movie_nodes(fixture_slide1["events"])[1])
    events = copy.deepcopy(data["events"])
    events[-1]["effects"][0]["effects"] = events[-1]["effects"][0].get("effects", []) + [
        {"movie": stray["movie"], "baseLayer": stray["baseLayer"], "effects": []}
    ]
    return {**data, "events": events}


def test_only_p2_measured_plans_are_qualified():
    # Codex (2026-09-19): the runtime keeps every decoded movie, honours only the first
    # restart and the first bridge, and picks same-asset instances in DOM order. Until it
    # is boundary-specific a deck is trusted only if its runtime plan is byte-for-byte one
    # the P2 gate measured. The fixture is; the same deck with a different slide-4
    # destination is a different, unmeasured plan and must fall back to the raw player.
    from dataclasses import replace

    from obed_edom import live_continuity

    plan = _plan()
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert live_continuity.plan_signature(runtime) in live_continuity.QUALIFIED_PLAN_SHA256

    boundaries = list(plan.boundaries)
    index = next(i for i, b in enumerate(boundaries) if any(m.action == "bridge" for m in b.movies))
    moved = tuple(
        replace(m, dst_rect=replace(m.dst_rect, x=m.dst_rect.x + 40)) if m.action == "bridge" else m
        for m in boundaries[index].movies
    )
    boundaries[index] = replace(boundaries[index], movies=moved)
    unmeasured = replace(plan, boundaries=tuple(boundaries)).to_runtime()
    assert isinstance(unmeasured, Unsupported)
    assert "not yet qualified" in unmeasured.reason


def test_an_entry_that_names_no_instance_cannot_be_expressed():
    plan = _plan()
    extra = MovieContinuity('second.mov', 'pin', Rect(0, 0, 100, 100), Rect(0, 0, 100, 100))
    bridge = replace(plan.boundaries[2], movies=(*plan.boundaries[2].movies, extra))
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert result == Unsupported("pin of 'second.mov' at scene 8 does not name its source instance")


# --- per-boundary refusal: overlapping artwork on the destination slide -------------------
#
# The destination slide's draw order is explicit in the export: every event carries
# `baseLayer.layers`, a flat back-to-front list of one wrapper slot per authored object, and the
# movie node's `objectID` names its own slot exactly. A Magic Move may carry a live movie across
# a boundary only when NOTHING authored above it overlaps its painted rect on the far side --
# otherwise the carried <video> would paint over artwork the author put in front of it.
#
# On the fixture's slide 2 that is the green square (draw slot 6, above the movie's slot 5). The
# black box at (543, 722, 181, 161) overlaps the movie geometrically too, but it is slot 1 --
# BEHIND -- and must not refuse; the rule reads z-order, not rects alone.


def test_fixture_refuses_only_the_1_to_2_boundary_and_names_the_green_squares_slot():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == (
        {
            "fromPlayer": 0,
            "toPlayer": 1,
            "atScene": P2_SLIDE2_MIN_HASH,
            "asset": "untitled.mov",
            "movieKey": "movie1",
            "reason": (
                "later-authored artwork overlaps the carried 'untitled.mov' on the destination "
                f"slide (player index 1, draw slot {SLIDE2_GREEN_SLOT})"
            ),
            "code": "overlap",
            "objectId": P2_OBJECT_IDS["slide1"],
        },
    )
    # the refusal lives on the boundary's own MovieContinuity too, and `action` still says pin.
    pinned = plan.boundaries[0].movies[0]
    assert pinned.action == "pin"
    assert pinned.refusal == plan.refusals[0]["reason"]
    # the 3->4 bridge's destination has nothing above the movie, so it is not refused.
    assert all(m.refusal is None for m in plan.boundaries[2].movies)


def test_refusals_are_not_part_of_the_runtime_plan():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert set(runtime) == {"schema", "movies", "boundaries"}
    assert "refusal" not in json.dumps(runtime)
    assert plan.as_dict()["refusals"] == [dict(r) for r in plan.refusals]
    assert json.loads(plan.to_json())["refusals"] == plan.as_dict()["refusals"]


def test_slide_instances_are_unchanged_by_the_refusal():
    """The refusal is a carry decision, not a geometry one: every authored instance is still
    ground truth for what must be visibly live on its slide."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances == {
        # slide 1 authors two Untitled.mov instances: the big continuing one and the second,
        # non-continuing one at ~(1076, 876) that `slide_rects` drops entirely.
        0: {"untitled.mov": [_rect(*SLIDE1_BIG), _rect(*SLIDE1_SMALL)]},
        1: {"untitled.mov": [_rect(*SLIDE1_BIG)]},
        # WA0125 never continues across a boundary, so it appears in no MovieContinuity and in
        # no runtime movie table -- but it is authored on slide 3 and must be visibly live there.
        2: {
            "untitled.mov": [_rect(*SLIDE3_UNTITLED)],
            "vid-20250608-wa0125.mp4": [_rect(*SLIDE3_WA0125)],
        },
        3: {"untitled.mov": [_rect(*SLIDE4_UNTITLED)]},
    }


def _move_green_square_below_the_movie(data):
    """Swap slide 2's draw slots 5 and 6 so the green square is authored BEHIND the movie."""
    for index in range(len(data["events"])):
        slots = _draw_slots(data, index)
        if len(slots) <= SLIDE2_GREEN_SLOT:
            continue
        slots[SLIDE2_MOVIE_SLOT], slots[SLIDE2_GREEN_SLOT] = (
            slots[SLIDE2_GREEN_SLOT], slots[SLIDE2_MOVIE_SLOT],
        )
    return data


def _plan_with_green_square_below() -> ContinuityPlan:
    plan = _plan(_mutate_slide(SLIDE2, _move_green_square_below_the_movie))
    assert isinstance(plan, ContinuityPlan)
    return plan


def test_green_square_authored_below_the_movie_does_not_refuse():
    """The same overlapping rect one draw slot lower is behind the movie, which is exactly the
    black box's situation on the real fixture -- it must be carried, not refused."""
    plan = _plan_with_green_square_below()
    assert plan.refusals == ()
    assert all(m.refusal is None for b in plan.boundaries for m in b.movies)


def test_no_retire_is_emitted_when_nothing_is_refused(monkeypatch):
    from obed_edom import live_continuity

    plan = _plan_with_green_square_below()
    # that plan is the pre-baseline shape, which the allowlist no longer carries; the assertion
    # here is about the derived boundaries, not about qualification.
    monkeypatch.setattr(
        live_continuity, "plan_signature", lambda _runtime: next(iter(live_continuity.QUALIFIED_PLAN_SHA256))
    )
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert [b["action"] for b in runtime["boundaries"]] == ["pin", "restart", "bridge"]


def test_overlap_in_a_later_event_only_still_refuses():
    """An object that builds in on click sits in the slot list from event 0, so this is the
    conservative case the export cannot distinguish: artwork in ANY event of the destination
    slide refuses, not only in its first."""

    def build_in_over_the_movie(data):
        data = _move_green_square_below_the_movie(data)
        movie_id = _slot_object(data, 0, SLIDE2_GREEN_SLOT)["objectID"]
        assert movie_id == "F9AFED1B-E2D7-47D4-942E-14992C808383"
        last = _events_drawing(data, movie_id)[-1]
        _draw_slots(data, last).append(_authored_slot(*_rect_of_movie_on_slide2(), object_id="BUILT-IN"))
        return data

    plan = _plan(_mutate_slide(SLIDE2, build_in_over_the_movie))
    assert isinstance(plan, ContinuityPlan)
    assert len(plan.refusals) == 1
    assert "draw slot 7" in plan.refusals[0]["reason"]


def _rect_of_movie_on_slide2() -> tuple[float, float, float, float]:
    """The painted (video sub-layer) rect the overlap rule compares against, to full authored
    precision -- `SLIDE1_BIG` is rounded, which matters at a 1px threshold."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    rect = plan.slide_instances[1]["untitled.mov"][0]
    return rect["x"], rect["y"], rect["w"], rect["h"]


@pytest.mark.parametrize("overlap, refusals", [(0.0, 0), (0.5, 0), (1.0, 0), (1.6, 1)])
def test_artwork_must_overlap_the_movie_by_more_than_the_minimum_to_refuse(overlap, refusals):
    """`_OVERLAP_MIN_PX` is 1.0 authored px and the intersection must be wider AND taller than
    it, so abutting edges and anti-aliasing seams are not a refusal."""
    x, y, w, _h = _rect_of_movie_on_slide2()

    def overlap_the_right_edge(data):
        data = _move_green_square_below_the_movie(data)
        _draw_slots(data, 0).append(_authored_slot(x + w - overlap, y, 400.0, 400.0, object_id="OVER"))
        return data

    plan = _plan(_mutate_slide(SLIDE2, overlap_the_right_edge))
    assert isinstance(plan, ContinuityPlan)
    if refusals:
        assert len(plan.refusals) == refusals
    else:
        assert plan.refusals == ()


def test_movie_slot_absent_in_one_event_is_skipped_not_refused():
    """Slide 2's last event is the flattened transition frame: a single canvas-sized slot with
    no objectID at all. It carries no draw order for the movie and must simply be skipped."""

    def drop_the_movie_slot_from_the_first_event(data):
        data = _move_green_square_below_the_movie(data)
        movie_id = _slot_object(data, 0, SLIDE2_GREEN_SLOT)["objectID"]
        drawn = _events_drawing(data, movie_id)
        assert len(drawn) < len(data["events"]), "the flattened event must already lack the movie"
        del _draw_slots(data, drawn[0])[SLIDE2_GREEN_SLOT]
        return data

    plan = _plan(_mutate_slide(SLIDE2, drop_the_movie_slot_from_the_first_event))
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()


# --- interim mask rule ---------------------------------------------------------------------
#
# This export family encodes no mask at all: `masksToBounds` is false, `contentsRect` is the unit
# rect, there is no `shapePath`, and the movie node's subtree uses a closed key vocabulary (plan
# section 0). Until a masked deck is exported and the real encoding is measured, anything outside
# that vocabulary may BE the mask -- and a masked movie must not even supply a `slide_instances`
# rect, so the rule lives in `_movie_rect` and applies to every movie node.


def _mask_reason_plan(uuid: str, transform) -> Unsupported:
    plan = _plan(_mutate_slide(uuid, transform))
    assert isinstance(plan, Unsupported), plan
    assert "possible mask" in plan.reason, plan.reason
    return plan


def test_a_contents_rect_within_the_measurement_tolerance_is_not_refused():
    def jitter(node):
        node["baseLayer"]["layers"][0]["initialState"]["contentsRect"]["width"] = 1 - 5e-7

    plan = _plan(_mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, jitter)))
    assert isinstance(plan, ContinuityPlan)


@pytest.mark.parametrize(
    "place, expected",
    [
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0]["initialState"].__setitem__("masksToBounds", True),
            "<movie node>.baseLayer.layers[0].initialState.masksToBounds",
            id="masksToBounds-on-the-video-sub-layer",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0]["initialState"]["contentsRect"].__setitem__("width", 0.5),
            "contentsRect.width",
            id="non-unit-contentsRect-is-a-possible-crop",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["initialState"].__setitem__("shapePath", {"elements": []}),
            "initialState.shapePath",
            id="shapePath-key-in-a-measured-container-by-name",
        ),
        # `texturedRectangle` is a leaf object the geometry rules never read, so a shallow check
        # would let anything through it.
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0].__setitem__("texturedRectangle", {"textureType": 0, "cornerRadius": 8}),
            "texturedRectangle.cornerRadius",
            id="unknown-key-deep-inside-a-measured-container",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0]["initialState"]["position"].__setitem__(
                "pointX", node["baseLayer"]["layers"][0]["initialState"]["position"]["pointX"] + 200
            ),
            "the video sub-layer is not contained in its movie layer",
            id="video-sub-layer-outside-its-movie-layer",
        ),
        # Any key outside the measured vocabulary, at every level.
        pytest.param(lambda node: node.__setitem__("maskLayer", {}), "<movie node>.maskLayer", id="vocabulary-node"),
        pytest.param(lambda node: node["baseLayer"].__setitem__("mask", {}), "<movie node>.baseLayer.mask", id="vocabulary-layer"),
        pytest.param(
            lambda node: node["baseLayer"]["initialState"].__setitem__("cornerRadius", 8),
            "<movie node>.baseLayer.initialState.cornerRadius",
            id="vocabulary-initialState",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0].__setitem__("mask", {}),
            "<movie node>.baseLayer.layers[0].mask",
            id="vocabulary-video-layer",
        ),
        # Every container the walk can reach, and the shape of the object that must not appear in
        # it. `effects` is always an empty list under a movie node, so an object inside one is an
        # encoding this module has never seen -- the mask could hide there without touching a
        # single checked key, which is exactly the hole a shallow key check leaves open.
        pytest.param(
            lambda node: node.__setitem__("effects", [{"shapePath": {"elements": []}}]),
            "<movie node>.effects[0]",
            id="shapePath-inside-an-unmeasured-container",
        ),
        pytest.param(
            lambda node: node.__setitem__("effects", [{"maskLayer": {"opacity": 1}}]),
            "<movie node>.effects[0]",
            id="effects-entry",
        ),
        pytest.param(
            lambda node: node["baseLayer"].__setitem__("animations", [{"property": "bounds"}]),
            "<movie node>.baseLayer.animations[0]",
            id="animations-entry",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0].__setitem__("texture", {"mask": "m"}),
            "<movie node>.baseLayer.layers[0].texture",
            id="texture-object",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["initialState"].__setitem__("affineTransform", [{"a": 1}]),
            "<movie node>.baseLayer.initialState.affineTransform[0]",
            id="transform-entry",
        ),
    ],
)
def test_an_unmeasured_movie_encoding_is_refused_as_a_possible_mask(place, expected):
    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, place))
    assert plan.reason.endswith(expected)


def test_a_mask_object_on_the_bridge_movie_cannot_qualify(monkeypatch):
    """Codex r1's blocker, verbatim: `effects: [{"maskLayer": ...}]` on slide 4's bridge movie
    moves no checked key and no geometry, so a shallow rule leaves the runtime plan -- and its
    allowlisted signature -- intact, and the runtime carries and paints the full UNMASKED video.
    It must be `Unsupported` even with the signature check disabled entirely."""
    from obed_edom import live_continuity

    def mask(node):
        node["effects"] = [{"maskLayer": {"opacity": 1}}]

    monkeypatch.setattr(
        live_continuity, "plan_signature", lambda _runtime: next(iter(live_continuity.QUALIFIED_PLAN_SHA256))
    )
    plan = _plan(_mutate_slide(SLIDE4, lambda data: _map_movie_nodes(data, mask)))
    assert isinstance(plan, Unsupported)
    assert "possible mask" in plan.reason


@pytest.mark.parametrize("name", ["maskLayer", "maskPath", "clipRect", "shouldClip", "shapePathRef"])
def test_a_key_that_reads_like_clipping_is_refused_wherever_it_appears(name):
    """Belt and braces over the vocabulary: even if a future measurement widens a key set, a
    name containing mask/clip/shapepath must never pass silently."""

    def tamper(node):
        node["movie"][name] = 1

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, tamper))
    assert plan.reason.endswith(f"<movie node>.movie.{name}")


def test_the_only_mask_named_keys_exempted_are_ones_the_export_really_carries():
    """Two measured keys contain 'mask' benignly; exempting anything else would reopen the hole
    the name rule closes."""
    from obed_edom import live_continuity

    measured = _measured_subtree_vocabulary(FIXTURE_ROOT)["initialState"]
    assert live_continuity._BENIGN_MASK_KEYS <= measured
    assert _plan().refusals[0]["toPlayer"] == 1, "the fixture still derives, exemptions included"


@pytest.mark.parametrize("value", [[], None, 0, "x", [0, 0, 1, 1], {"x": 0, "y": 0, "width": 1}])
def test_a_contents_rect_that_is_not_the_unit_object_is_refused(value):
    """A falsey or wrongly-shaped `contentsRect` must not be read as 'no crop': that is how a
    malformed export would slip a crop past the rule."""

    def tamper(node):
        node["baseLayer"]["layers"][0]["initialState"]["contentsRect"] = value

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, tamper))
    assert plan.reason.endswith("initialState.contentsRect")


@pytest.mark.parametrize("value", [True, False, 1, 0, "false", None])
def test_masks_to_bounds_must_be_exactly_false(value):
    def tamper(node):
        node["baseLayer"]["initialState"]["masksToBounds"] = value

    if value is False:
        plan = _plan(_mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, tamper)))
        assert isinstance(plan, ContinuityPlan)
        return
    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, tamper))
    assert plan.reason.endswith("initialState.masksToBounds")


# --- malformed shapes fail closed, they never raise ----------------------------------------


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda state: state.pop("initialState"), id="no-initialState"),
        pytest.param(lambda state: state["initialState"].pop("width"), id="no-width"),
        pytest.param(lambda state: state["initialState"].pop("height"), id="no-height"),
        pytest.param(lambda state: state["initialState"].pop("position"), id="no-position"),
        pytest.param(lambda state: state["initialState"]["position"].pop("pointY"), id="no-pointY"),
        pytest.param(lambda state: state["initialState"].__setitem__("width", "wide"), id="text-width"),
        pytest.param(lambda state: state["initialState"].__setitem__("width", None), id="null-width"),
        pytest.param(lambda state: state["initialState"].__setitem__("height", True), id="bool-height"),
        pytest.param(
            lambda state: state["initialState"]["position"].__setitem__("pointX", float("nan")),
            id="nan-pointX",
        ),
        pytest.param(lambda state: state.__setitem__("initialState", []), id="list-initialState"),
    ],
)
def test_a_malformed_slot_above_the_movie_is_unsupported_not_an_exception(tamper):
    def break_the_green_square(data):
        tamper(_slot_object(data, 0, SLIDE2_GREEN_SLOT))
        return data

    plan = _plan(_mutate_slide(SLIDE2, break_the_green_square))
    assert isinstance(plan, Unsupported)


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda layer: layer.pop("initialState"), id="no-initialState"),
        pytest.param(lambda layer: layer["initialState"].pop("width"), id="no-width"),
        pytest.param(lambda layer: layer["initialState"].__setitem__("height", "tall"), id="text-height"),
        pytest.param(lambda layer: layer["initialState"].pop("position"), id="no-position"),
        pytest.param(lambda layer: layer.__setitem__("initialState", []), id="list-initialState"),
        pytest.param(lambda layer: layer.__setitem__("layers", "not a list"), id="text-layers"),
    ],
)
def test_a_malformed_movie_layer_is_unsupported_not_an_exception(tamper):
    plan = _plan(_mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, lambda n: tamper(n["baseLayer"]))))
    assert isinstance(plan, Unsupported)


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda state: state.__setitem__("affineTransform", None), id="null-affine"),
        pytest.param(lambda state: state.__setitem__("affineTransform", [1, 0, 0, 1]), id="short-affine"),
        pytest.param(lambda state: state.__setitem__("affineTransform", "identity"), id="text-affine"),
        pytest.param(
            lambda state: state.__setitem__("affineTransform", [1, 0, 0, 1, 0, float("nan")]),
            id="nan-affine-element",
        ),
        pytest.param(
            lambda state: state.__setitem__("affineTransform", [1, 0, 0, 1, 0, "0"]), id="text-affine-element",
        ),
        pytest.param(lambda state: state.__setitem__("anchorPoint", []), id="list-anchorPoint"),
        pytest.param(lambda state: state.__setitem__("anchorPoint", None), id="null-anchorPoint"),
        pytest.param(lambda state: state["anchorPoint"].pop("pointX"), id="no-pointX"),
        pytest.param(
            lambda state: state["anchorPoint"].__setitem__("pointY", float("inf")), id="inf-pointY",
        ),
        pytest.param(lambda state: state.__setitem__("rotation", float("nan")), id="nan-rotation"),
        pytest.param(lambda state: state.__setitem__("rotation", "0"), id="text-rotation"),
        pytest.param(lambda state: state.__setitem__("scale", float("nan")), id="nan-scale"),
        pytest.param(
            lambda state: state["contentsRect"].__setitem__("width", float("nan")), id="nan-contentsRect",
        ),
        pytest.param(
            lambda state: state["contentsRect"].__setitem__("width", float("inf")), id="inf-contentsRect",
        ),
    ],
)
def test_a_malformed_transform_or_anchor_is_unsupported_not_an_exception(tamper):
    """Python's `json` parses NaN and Infinity, and a NaN compares false against every bound, so
    a plain `abs(value - unit) > tol` check would wave it straight through. Every number in the
    geometry path is read as a finite number or not at all."""
    plan = _plan(
        _mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, lambda n: tamper(n["baseLayer"]["initialState"])))
    )
    assert isinstance(plan, Unsupported)


def test_python_json_really_does_accept_nan_so_the_guard_is_not_theoretical():
    assert math.isnan(json.loads('{"width": NaN}')["width"])


def _measured_subtree_vocabulary(root: Path) -> dict[str, set[str]]:
    """Every object under every movie node of an export, keyed by the key that holds it."""
    measured: dict[str, set[str]] = {}

    def walk(value, kind):
        if isinstance(value, list):
            for item in value:
                walk(item, kind)
        elif isinstance(value, dict):
            measured.setdefault(kind, set()).update(value)
            for key, child in value.items():
                walk(child, key)

    uuids = json.loads((root / "assets" / "header.json").read_text())["slideList"]
    for uuid in uuids:
        data = json.loads((root / "assets" / uuid / f"{uuid}.json").read_text())
        for node in _find_movie_nodes(data["events"]):
            walk(node, "<movie node>")
    return measured


def test_the_measured_vocabulary_does_not_refuse_todays_fixture():
    """The allowlist is only honest if it is a measurement: every object the fixture actually
    contains, at every depth, must be in the table, or the rule would refuse the deck P2
    qualified."""
    from obed_edom import live_continuity

    measured = _measured_subtree_vocabulary(FIXTURE_ROOT)
    for kind, keys in measured.items():
        assert kind in live_continuity._MOVIE_SUBTREE_KEYS, kind
        assert keys <= live_continuity._MOVIE_SUBTREE_KEYS[kind], (kind, keys)
    assert "objectID" in measured["<movie node>"], "the overlap rule needs the movie objectIDs"


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_the_measured_vocabulary_is_the_real_exports_and_nothing_more():
    """The table is measured from the REAL export, which carries containers the trim dropped
    (`attributes`, `texture`, `texturedRectangle`, `baseLayer.objectID`). It must cover the real
    export exactly -- no gaps, and no entry invented beyond what was measured."""
    from obed_edom import live_continuity

    measured = _measured_subtree_vocabulary(REAL_PLAYER_ROOT)
    # `movie.loopMode` is the one key measured elsewhere: the owner's Repeat -> Loop export
    # (`output/fixtures/p2-soak-loop`, parity-tested in test_live_continuity_decks.py). P2's export
    # carries no looping movie, so the key must be absent there and is added by hand.
    assert "loopMode" not in measured["movie"]
    measured["movie"].add("loopMode")
    assert set(measured) == set(live_continuity._MOVIE_SUBTREE_KEYS)
    for kind, keys in measured.items():
        assert keys == set(live_continuity._MOVIE_SUBTREE_KEYS[kind]), kind
    # the containers that never hold an object are deliberately absent from the table.
    for never_an_object in ("effects", "animations", "texture", "affineTransform", "sublayerTransform"):
        assert never_an_object not in live_continuity._MOVIE_SUBTREE_KEYS


# --- `retire` in the runtime plan -----------------------------------------------------------


def _refused_pin(plan: ContinuityPlan, boundary_index: int, **changes):
    boundary = plan.boundaries[boundary_index]
    return replace(
        boundary,
        movies=tuple(replace(m, refusal="synthetic refusal") for m in boundary.movies),
        **changes,
    )


def test_a_refused_bridge_retires_only_its_own_boundary(monkeypatch):
    """Refusals are per boundary (plan section 2.3): a refused bridge becomes a `retire` of its
    source instance and the rest of the deck is still planned."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    refused_bridge = _refused_pin(plan, 2)
    runtime = _signed(monkeypatch, replace(plan, boundaries=(*plan.boundaries[:2], refused_bridge, plan.boundaries[3])))
    assert runtime["boundaries"][2] == {
        "atScene": 8, "action": "retire", "movieKey": "movie1", "reason": "refused",
        "src": EXPECTED_RUNTIME_PLAN["boundaries"][2]["src"],
    }
    assert runtime["boundaries"][:2] == EXPECTED_RUNTIME_PLAN["boundaries"][:2]


def test_a_refused_bridge_derived_from_the_export_retires_its_boundary(monkeypatch):
    """The same thing end to end: put an object over the movie on slide 4, the 3->4 bridge's
    destination, and that boundary alone is refused."""

    def cover_the_movie(data):
        movie_id = _slot_object(data, 0, 1)["objectID"]
        assert movie_id == P2_OBJECT_IDS["slide4"]
        _draw_slots(data, 0).append(_authored_slot(*SLIDE4_UNTITLED, object_id="COVER"))
        return data

    plan = _plan(_mutate_slide(SLIDE4, cover_the_movie))
    assert isinstance(plan, ContinuityPlan)
    assert [(r["toPlayer"], r["code"], r["objectId"]) for r in plan.refusals] == [
        (1, "overlap", P2_OBJECT_IDS["slide1"]), (3, "overlap", P2_OBJECT_IDS["slide3"]),
    ]
    runtime = _signed(monkeypatch, plan)
    assert [(b["atScene"], b["action"], b.get("reason")) for b in runtime["boundaries"]] == [
        (2, "retire", "refused"), (6, "restart", None), (8, "retire", "refused"),
    ]


def test_a_refusal_on_a_restart_boundary_becomes_a_retire(monkeypatch):
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    refused_restart = _refused_pin(plan, 1)
    runtime = _signed(monkeypatch, replace(plan, boundaries=(plan.boundaries[0], refused_restart, *plan.boundaries[2:])))
    assert [(b["atScene"], b["action"], b.get("reason")) for b in runtime["boundaries"]] == [
        (2, "retire", "refused"), (6, "retire", "refused"), (8, "bridge", None),
    ]
    assert "dst" not in runtime["boundaries"][1]


def test_an_unrefused_retire_ends_a_carried_instance():
    plan = _plan()
    ends = MovieContinuity(
        "untitled.mov", "retire", Rect(1, 2, 3, 4), None, src_object_id="HELD", loop=True,
    )
    boundary = replace(plan.boundaries[1], movies=(ends,))
    from obed_edom.live_continuity import _runtime_entry

    assert _runtime_entry(plan, boundary, ends, 6, "movie1") == {
        "atScene": 6, "action": "retire", "reason": "ends", "movieKey": "movie1",
        "src": {"objectId": "HELD", "rect": {"x": 1, "y": 2, "w": 3, "h": 4}},
    }


# --- I5 codec report -----------------------------------------------------------------------

def test_codec_report_lists_every_referenced_movie_and_fails_closed_without_its_bytes():
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    # The fixture's WA0125 instance never continues across a boundary (only Untitled.mov
    # does), so it is never part of a continuity plan; the codec report must still list it.
    assert {entry["asset"] for entry in report} == {"untitled.mov", "vid-20250608-wa0125.mp4"}
    for entry in report:
        assert set(entry) == {"asset", "codec", "family", "files"}
        # tests/fixtures/live_continuity ships only the export JSON, not the referenced .mov
        # bytes, so every entry must fail closed to an unreadable/"other" codec, not raise.
        assert entry["codec"] is None
        assert entry["family"] == "other"


def test_codec_report_skips_slides_it_cannot_read_instead_of_raising():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / SLIDE1 / f"{SLIDE1}.json").write_text("not json at all")
    report = codec_report(tmp, SLIDES, resolver=_resolver)
    assets = {entry["asset"] for entry in report}
    # slide 1 is unreadable and contributes nothing, but the other slides still do.
    assert "vid-20250608-wa0125.mp4" in assets


def _tree_with_movie_files() -> Path:
    """The fixture ships no .mov bytes. An HTML export stores a separate copy of the movie
    under every slide folder that uses it, so write a placeholder for each: the codec of
    each copy is then supplied by an injected probe."""
    tmp = _copy_fixture_tree()
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        data = json.loads((tmp / "assets" / uuid / f"{uuid}.json").read_text())
        for entry in data["assets"].values():
            path = tmp / "assets" / uuid / entry["url"]["web"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
    return tmp


def _probe_by_slide(codecs: dict[str, str | None]):
    """Report a codec per slide folder: a path resolves to assets/<uuid>/assets/<file>."""
    return lambda path: codecs.get(path.parent.parent.name)


def _entry(report: list[dict], asset: str) -> dict:
    return next(entry for entry in report if entry["asset"] == asset)


@pytest.mark.parametrize(
    "slide3_codec, expected",
    [
        pytest.param("avc1", {"codec": "avc1", "family": "h264"}, id="every-copy-agrees"),
        # Slide 1's copy is H.264 but slide 3's separate file is HEVC: keeping only the first
        # would report the key playable while a fresh decoder on slide 3 cannot play it.
        pytest.param("hvc1", {"codec": None, "family": "other", "mixed": True}, id="one-copy-is-a-different-codec"),
        # unreadable, not "mixed": the key's codec is simply unknown.
        pytest.param(None, {"codec": None, "family": "other"}, id="one-copy-is-unreadable"),
    ],
)
def test_codec_report_aggregates_every_slide_folders_copy_of_one_asset(slide3_codec, expected):
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide({SLIDE1: "avc1", SLIDE2: "avc1", SLIDE3: slide3_codec, SLIDE4: "avc1"})
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    assert _entry(report, "untitled.mov") == {"asset": "untitled.mov", **expected, "files": 4}


def test_codec_report_keeps_two_different_assets_independent():
    tmp = _tree_with_movie_files()
    report = codec_report(
        tmp, SLIDES, resolver=_resolver,
        probe=lambda path: "hvc1" if path.name.startswith("VID-") else "avc1",
    )
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": "avc1", "family": "h264", "files": 4,
    }
    assert _entry(report, "vid-20250608-wa0125.mp4") == {
        "asset": "vid-20250608-wa0125.mp4", "codec": "hvc1", "family": "hevc", "files": 1,
    }


def test_codec_report_omits_fps_unless_requested():
    tmp = _tree_with_movie_files()
    probed = []
    report = codec_report(
        tmp, SLIDES, resolver=_resolver, probe=lambda _path: "avc1", probe_fps=lambda path: probed.append(path) or 25.0,
    )
    assert all("fps" not in entry for entry in report)
    assert probed == []


def test_codec_report_rounds_fps_agreed_by_every_slide_folders_copy():
    tmp = _tree_with_movie_files()
    report = codec_report(
        tmp, SLIDES, resolver=_resolver, probe=lambda _path: "avc1", probe_fps=lambda _path: 30000 / 1001, with_fps=True,
    )
    assert _entry(report, "untitled.mov")["fps"] == 29.97


@pytest.mark.parametrize("slide3_fps", [pytest.param(30.0, id="copies-disagree"), pytest.param(None, id="one-copy-unreadable")])
def test_codec_report_fps_is_none_unless_every_copy_agrees(slide3_fps):
    tmp = _tree_with_movie_files()
    rates = {SLIDE1: 25.0, SLIDE2: 25.0, SLIDE3: slide3_fps, SLIDE4: 25.0}
    report = codec_report(
        tmp, SLIDES, resolver=_resolver, probe=lambda _path: "avc1",
        probe_fps=lambda path: rates.get(path.parent.parent.name), with_fps=True,
    )
    entry = _entry(report, "untitled.mov")
    assert entry["fps"] is None
    # an fps disagreement never touches the codec verdict.
    assert entry["codec"] == "avc1"
    assert "mixed" not in entry


def test_codec_report_counts_one_file_for_two_instances_of_the_same_movie_on_a_slide():
    # Slide 1 authors Untitled.mov twice; both instances are the same file on disk.
    tmp = _tree_with_movie_files()
    slides = [SLIDES[0]]
    report = codec_report(tmp, slides, resolver=_resolver, probe=lambda _path: "avc1")
    assert _entry(report, "untitled.mov")["files"] == 1


def test_codec_report_on_slides_with_no_movies_is_empty():
    slides = [{"playerIndex": 0, "originalOrdinal": 1, "exportedUuid": SLIDE2, "skipped": False}]
    report = codec_report(FIXTURE_ROOT, slides, resolver=_resolver)
    # slide 2 has no non-continuing single-instance movie of its own referenced beyond
    # what boundary 1 already covers; this only asserts the call is well-formed and
    # never raises on a minimal slide list.
    assert isinstance(report, list)


# --- slide_instances: ground truth for the visible-content probe --------------------------
#
# `slide_rects` keeps an asset only when the slide authors exactly ONE instance of it
# (live_continuity.py: `if len(rects) == 1`), so it cannot describe slide 1's two
# Untitled.mov instances. `slide_instances` lists EVERY authored movie instance per player
# index -- multi-instance assets and movies that no boundary classifies included -- ordered
# by (x, y, w, h) ascending.

SLIDE1_BIG = (109.35, 795.04, 951.54, 267.62)
SLIDE1_SMALL = (1075.79, 876.25, 662.79, 186.41)
SLIDE3_UNTITLED = (197.98, 797.10, 951.54, 267.62)
SLIDE3_WA0125 = (1152.72, 794.60, 484.66, 272.62)
SLIDE4_UNTITLED = (326.75, 708.52, 1266.49, 356.20)


def test_slide_instances_matches_slide_rects_where_an_asset_is_single_instance():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    for player_index, rects in plan.slide_rects.items():
        for asset, rect in rects.items():
            assert plan.slide_instances[player_index][asset] == [rect]
    # slide 1's two Untitled.mov instances (test_slide_instances_are_unchanged_by_the_refusal)
    # contribute nothing to slide_rects, which drops multi-instance assets.
    assert plan.slide_rects[0] == {}


def test_slide_instances_covers_every_player_index_and_uses_movie_rect_geometry():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert set(plan.slide_instances) == set(plan.scene_index_by_player) == {0, 1, 2, 3}
    assert plan.slide_instances[1] == {"untitled.mov": [_rect(*SLIDE1_BIG)]}
    # the rects are the authored-space rects _movie_rect produces for the boundaries too.
    bridge = next(m for m in _boundary(plan, 2)["movies"] if m["asset"] == "untitled.mov")
    assert plan.slide_instances[2]["untitled.mov"][0] == bridge["srcRect"]
    assert plan.slide_instances[3]["untitled.mov"][0] == bridge["dstRect"]


def test_slide_instances_ordering_is_deterministic_and_independent_of_authoring_order():
    """Instances sort by (x, y, w, h) ascending. Slide 1's two Untitled.mov instances live in
    different branches of the event tree, so swapping their geometry swaps the DOM order the
    rects are discovered in; the emitted field must be identical either way."""

    def swap_instance_geometry(data):
        events = copy.deepcopy(data["events"])
        nodes = _find_movie_nodes(events)
        assert len(nodes) == 2, "slide 1 fixture must author two movie instances"
        first, second = nodes[0]["baseLayer"], nodes[1]["baseLayer"]
        nodes[0]["baseLayer"], nodes[1]["baseLayer"] = second, first
        return {**data, "events": events}

    baseline = _plan()
    assert isinstance(baseline, ContinuityPlan)
    swapped = _plan(_mutate_slide(SLIDE1, swap_instance_geometry))
    assert isinstance(swapped, ContinuityPlan)
    assert swapped.slide_instances == baseline.slide_instances
    assert (
        swapped.slide_instances[0]["untitled.mov"][0]["x"]
        < swapped.slide_instances[0]["untitled.mov"][1]["x"]
    )


def test_slide_instances_defaults_to_empty_so_positional_construction_still_works():
    plan = ContinuityPlan({"width": 1, "height": 1}, {0: 0}, {}, ())
    assert plan.slide_instances == {}
    assert plan.as_dict()["slideInstances"] == {}


def test_slide_instances_does_not_move_the_runtime_plan_or_its_signature():
    """The visible-content ground truth is additive: `to_runtime()` must not learn about it,
    so the allowlisted signature (and P2's injected plan) stay exactly where they are."""
    from obed_edom import live_continuity

    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert set(runtime) == {"schema", "movies", "boundaries"}
    assert "slideInstances" not in json.dumps(runtime)
    assert "slide_instances" not in json.dumps(runtime)
    assert live_continuity.plan_signature(runtime) == EXPECTED_PLAN_SHA256
    assert live_continuity.plan_signature(runtime) in live_continuity.QUALIFIED_PLAN_SHA256
    # an emptied field must not change the runtime either.
    assert replace(plan, slide_instances={}).to_runtime() == runtime


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_slide_instances_match_the_trimmed_fixture():
    real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=_unchecked_resolver)
    fixture = _plan()
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.slide_instances == fixture.slide_instances


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_movies_report_h264():
    report = codec_report(REAL_PLAYER_ROOT, SLIDES, resolver=_unchecked_resolver)
    assert report
    for entry in report:
        assert entry["codec"] == "avc1"
        assert entry["family"] == "h264"
    # the export stores its own copy of Untitled.mov under each of the four slide folders,
    # and every one of them is probed.
    assert next(entry for entry in report if entry["asset"] == "untitled.mov")["files"] == 4


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_untitled_movie_reports_30_fps():
    report = codec_report(REAL_PLAYER_ROOT, SLIDES, resolver=_unchecked_resolver, with_fps=True)
    assert _entry(report, "untitled.mov")["fps"] == pytest.approx(30.0, abs=0.01)


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_yields_the_same_runtime_plan_and_refusal():
    """The trimmed fixture gained the draw-slot data the overlap rule reads; this is the check
    that it was copied faithfully, not authored to suit the rule."""
    real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=_unchecked_resolver)
    assert isinstance(real, ContinuityPlan)
    assert real.to_runtime() == EXPECTED_RUNTIME_PLAN
    fixture = _plan()
    assert isinstance(fixture, ContinuityPlan)
    assert real.refusals == fixture.refusals

# --- O0/O1: the glReplay transition-effect vocabulary and settled-opacity overrides --------
#
# `_check_effect_encoding`/`effect_opacity_overrides` are pure, importable functions the G1
# arming work will call once `derive_plan` emits a `glReplay` boundary (not built yet -- see
# the plan's O0/O1 rows). `_check_effect_encoding` is a single recursive schema
# (`_v_transition_effect`, built from small combinators in `live_continuity.py`): every
# container and every primitive reachable from it has an explicit validator, so a value cannot
# reach the arithmetic below without one. The unit tests below run unconditionally against
# `tests/fixtures/live_continuity/effect_1_to_2.json`, a sanitized (texture ids replaced with
# placeholders, every number kept) copy of the real fixture export's
# baseLayer.layers[1].effects[0] transition (the 1->2 magic move). Exactly one test is gated on
# `REAL_PLAYER_ROOT` (the real export is `output/**`, gitignored) and asserts the sanitized
# fixture's outputs equal the real export's, plus classifies every other effect in the export by
# its measured shape.

EFFECT_FIXTURE = FIXTURE_ROOT / "effect_1_to_2.json"

# m4_settled.py's settled-leaf-rect arithmetic, measured on the qualified export.
REAL_SLOT_SIZES = [[1920, 1080], [671, 195], [266, 236], [960, 276], [178, 157]]
REAL_SLOT_RECTS = [
    [0.0, 0.0, 1920, 1080],
    [1071.68, 871.95, 671, 195],
    [541.86, 721.08, 181.0, 161.0],
    [105.12, 790.85, 960, 276],
    [788.73, 672.92, 353.0, 313.0],
]
REAL_SLOT4_OPACITY = 0.29468628764152527


def _sanitized_effect() -> dict:
    return json.loads(EFFECT_FIXTURE.read_text())


def _mutate_sanitized_effect(transform) -> dict:
    effect = _sanitized_effect()
    transform(effect)
    return effect


def _leaf_of(node: dict) -> dict:
    while node.get("layers"):
        node = node["layers"][0]
    return node


def _scalar_group(from_value, to_value, property_: str = "opacity") -> dict:
    return {
        "additive": False, "timeOffset": 0, "beginTime": 0, "repeatCount": 0,
        "fillMode": "both", "duration": 0.1, "autoreverses": False,
        "animations": [
            {"repeatCount": 0, "removedOnCompletion": True, "from": {"scalar": from_value},
             "timingFunction": "EaseInEaseOut", "additive": False, "timeOffset": 0,
             "autoreverses": False, "property": property_, "fillMode": "both",
             "duration": 0.1, "beginTime": 0, "to": {"scalar": to_value}}
        ], "removedOnCompletion": False,
    }


def _leaf_animation(effect: dict, slot: int, property_: str = "opacity") -> dict:
    leaf = _leaf_of(effect["baseLayer"]["layers"][slot])
    group = leaf["animations"][0]
    return next(a for a in group["animations"] if a.get("property") == property_)


def _slot_leaf(effect: dict, slot: int) -> dict:
    return _leaf_of(effect["baseLayer"]["layers"][slot])


def _nudge_x(state: dict, dx: float) -> None:
    state["position"]["pointX"] += dx


def _assert_is_the_qualified_1_to_2_result(result) -> None:
    assert not isinstance(result, Unsupported)
    assert isinstance(result, dict)
    assert result["slotSizes"] == REAL_SLOT_SIZES
    # REAL_SLOT_RECTS are copied from m4_settled.log, which prints rects at 2 dp.
    for got, want in zip(result["slotRects"], REAL_SLOT_RECTS):
        assert got == pytest.approx(want, abs=5e-3)
    assert len(result["opacityOverrides"]) == 1
    override = result["opacityOverrides"][0]
    assert override["slot"] == 4
    assert override["opacity"] == pytest.approx(REAL_SLOT4_OPACITY, abs=1e-9)
    assert override["texW"] == 178
    assert override["texH"] == 157
    assert result["excluded"] == [{"slot": 1, "reason": "fade"}]


def test_effect_fixture_present():
    assert EFFECT_FIXTURE.is_file()


def test_gl_replay_opacity_overrides_from_the_qualified_fixture():
    # `effect_opacity_overrides` runs `_check_effect_encoding` first, so this also proves the
    # effect-tree vocabulary is closed on the qualified fixture.
    _assert_is_the_qualified_1_to_2_result(effect_opacity_overrides(_sanitized_effect()))


# --- mutations of the sanitized 1->2 effect that need more than one statement ------------------


def _bare_leaf_under_a_layer_node(effect):
    """`layers[i].animations` must satisfy the GROUP schema; a bare leaf there has no
    `animations` key of its own, so `_v_animation_group`'s required-key check refuses it."""
    effect["baseLayer"]["layers"][0]["animations"] = [
        {"additive": False, "autoreverses": False, "beginTime": 0, "duration": 0.1,
         "fillMode": "both", "from": {"scalar": 1}, "property": "opacity",
         "removedOnCompletion": True, "repeatCount": 0, "timeOffset": 0, "to": {"scalar": 1}}
    ]


def _group_nested_inside_a_group(effect):
    """A group's own `animations` must satisfy the LEAF schema; a nested group has no
    `property` of its own, so `_v_animation_leaf`'s property check refuses it."""
    inner = {
        "additive": False, "animations": [], "autoreverses": False, "beginTime": 0,
        "duration": 0.1, "fillMode": "both", "removedOnCompletion": False,
        "repeatCount": 0, "timeOffset": 0,
    }
    effect["baseLayer"]["layers"][0]["animations"] = [{**inner, "animations": [inner]}]


def _skew_leaf_sublayer_transform(effect):
    state = _slot_leaf(effect, 4)["initialState"]
    matrix = list(state["sublayerTransform"])
    matrix[11] = 0.5
    state["sublayerTransform"] = matrix


def _add_wrapper_translation(effect):
    """`transform.translation`/`transform.scale.*` are only ever measured on a chain's leaf; one
    on the wrapper must refuse rather than being silently accepted and ignored."""
    wrapper = effect["baseLayer"]["layers"][4]
    wrapper["animations"] = [
        {"additive": False, "timeOffset": 0, "beginTime": 0, "repeatCount": 0,
         "fillMode": "both", "duration": 0.1, "autoreverses": False,
         "animations": [
             {"repeatCount": 0, "removedOnCompletion": True, "from": {"pointX": 0, "pointY": 0},
              "timingFunction": "EaseInEaseOut", "additive": False, "timeOffset": 0,
              "autoreverses": False, "property": "transform.translation", "fillMode": "both",
              "duration": 0.1, "beginTime": 0, "to": {"pointX": 100, "pointY": 0}}
         ], "removedOnCompletion": False},
        *(wrapper.get("animations") or []),
    ]


def _set_slot4_settled_scale(scale, *, centre_the_anchor: bool = False):
    def apply(effect):
        leaf = _slot_leaf(effect, 4)
        if centre_the_anchor:
            leaf["initialState"]["anchorPoint"] = {"pointX": 0.5, "pointY": 0.5}
        for anim in leaf["animations"][0]["animations"]:
            if anim.get("property") in ("transform.scale.x", "transform.scale.y"):
                anim["to"] = {"scalar": scale(anim)}

    return apply


def _negate_slot4_scale_x(effect):
    for anim in _slot_leaf(effect, 4)["animations"][0]["animations"]:
        if anim["property"] == "transform.scale.x":
            anim["to"] = {"scalar": -anim["to"]["scalar"]}


def _wrapper_gains_its_leafs_texture(effect):
    """The inverse of the leaf checks: a non-terminal node (it still has a child) must not ALSO
    carry `texture`/`texturedRectangle` -- a slot the offline schema cannot tell apart from a
    single textured draw when the player might render two."""
    wrapper = effect["baseLayer"]["layers"][4]
    leaf = _leaf_of(wrapper)
    wrapper["texture"] = leaf["texture"]
    wrapper["texturedRectangle"] = copy.deepcopy(leaf["texturedRectangle"])


def _negative_wrapper_width(effect):
    """A negative wrapper width, with the child's `position` adjusted to still satisfy the
    centred-in-parent residual for that (negative) width, must refuse on the wrapper's own
    non-positive size -- a flipped/negative wrapper is not something the rect formula (or any
    measured deck) ever produces."""
    wrapper = effect["baseLayer"]["layers"][4]
    wrapper["initialState"]["width"] = -wrapper["initialState"]["width"]
    _leaf_of(wrapper)["initialState"]["position"]["pointX"] = wrapper["initialState"]["width"] / 2


def _add_slot3_hidden_animation(effect):
    """Slot 3 has no `hidden` animation at all; adding one (with a measured-valid `fillMode`, so
    the animation itself is not what excludes it) must still exclude the slot -- `hidden`
    exclusion is presence-based, not conditioned on the animation being the settled one."""
    leaf = _slot_leaf(effect, 3)
    leaf["animations"] = [*(leaf.get("animations") or []), _scalar_group(False, False, "hidden")]


def _drop_slot1_hidden_animation(effect):
    """Slot 1 on the fixture carries both a fade and a `hidden` animation; isolate the fade alone
    to prove the fade path itself excludes rather than refuses, independent of the `hidden` rule."""
    group = _slot_leaf(effect, 1)["animations"][0]
    group["animations"] = [a for a in group["animations"] if a.get("property") != "hidden"]


def _three_factor_nan_product(effect):
    """`1e308 * 1e308` overflows to `inf` first; only the THIRD factor (`* 0`) produces the
    actual `nan` the round-2 regression was about. Slot 0's real chain is already three levels
    deep (`E.0 -> E.0.0 -> E.0.0.0`), so each level gets one of the three factors, in chain order."""
    wrapper = effect["baseLayer"]["layers"][0]
    mid = wrapper["layers"][0]
    leaf = mid["layers"][0]
    wrapper["animations"] = [_scalar_group(1e308, 1e308)]
    mid["animations"] = [_scalar_group(1e308, 1e308)]
    leaf["animations"] = [_scalar_group(0, 0)]
    leaf["texturedRectangle"]["singleTextureOpacity"] = 0


def _two_factor_overflow_product(effect):
    effect["baseLayer"]["layers"][0]["animations"] = [_scalar_group(1e308, 1e308)]
    _slot_leaf(effect, 0)["animations"] = [_scalar_group(1e308, 1e308)]


# --- schema refusals: `_check_effect_encoding` raises, so the public entry point is Unsupported --


@pytest.mark.parametrize(
    "mutate, match",
    [
        # Codex round 3 item A: one recursive schema closes every container AND every primitive.
        # Seven reproduced escapes (attributes=42, contentsRect="junk", shapePath="junk", malformed
        # points, a leaf directly under a layer-node's `animations`, a group nested inside a
        # group, an explicitly present `timingFunction=None`), three semantic escapes (see
        # test_rendering_sensitive_neutrals_are_pinned_to_their_measured_value), and unhashable
        # operands.
        pytest.param(lambda e: e.__setitem__("attributes", 42), "not a readable object", id="r3A-attributes-not-an-object"),
        pytest.param(
            lambda e: _slot_leaf(e, 0)["initialState"].__setitem__("contentsRect", "junk"),
            "not a readable object", id="r3A-contentsRect-not-an-object",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 4)["texturedRectangle"].__setitem__("shapePath", "junk"),
            "not a readable object", id="r3A-shapePath-not-an-object",
        ),
        pytest.param(_bare_leaf_under_a_layer_node, "unmeasured keys", id="r3A-leaf-directly-under-a-layer-nodes-animations"),
        pytest.param(_group_nested_inside_a_group, "property", id="r3A-group-nested-inside-a-group"),
        # Distinguishes 'absent' (fine, `timingFunction` is optional; see the accepted table) from
        # 'present but invalid'.
        pytest.param(
            lambda e: _leaf_animation(e, 4).__setitem__("timingFunction", None),
            "timingFunction", id="r3A-explicitly-present-invalid-timingFunction",
        ),
        # A list is unhashable; the old `dict.get(property_)`-style lookup would raise a raw
        # `TypeError` before ever reaching a `_Refuse`. The schema type-checks with `isinstance`.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["animations"][0]["animations"][0].__setitem__("property", ["opacity"]),
            "property", id="r3A-unhashable-property",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 4).__setitem__("fillMode", ["both"]), "fillMode", id="r3A-unhashable-fillMode",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 4)["texturedRectangle"]["shapePath"]["elements"][0].__setitem__("type", ["MoveToPoint"]),
            "type", id="r3A-unhashable-shapePath-element-type",
        ),
        # residual coverage from round 1/2, still meaningful under the new schema
        pytest.param(lambda e: e.__setitem__("movie", {"asset": "x"}), "unmeasured keys", id="r1r2-movie-key-on-the-transition-effect"),
        pytest.param(
            lambda e: e["baseLayer"]["layers"][1].__setitem__("isVideoLayer", True),
            "unmeasured keys", id="r1r2-isVideoLayer-on-an-effect-layer",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 4).__setitem__("to", {"pointX": 0, "pointY": 0}),
            "unmeasured keys", id="r1r2-opacity-with-a-point-value-shape",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 4).__setitem__("to", {"scalar": "not-a-number"}),
            "finite number", id="r1r2-opacity-with-a-non-numeric-scalar",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 1, "hidden").__setitem__("to", {"scalar": 1}),
            "readable boolean", id="r1r2-hidden-scalar-must-be-boolean-not-numeric",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 0, "contents").__setitem__("to", {"texture": ""}),
            "non-empty string", id="r1r2-contents-texture-must-be-a-non-empty-string",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 3).setdefault("animations", []).append(_scalar_group(True, False, "isPlaying")),
            "property", id="r1r2-unmeasured-animation-property",
        ),
        pytest.param(
            lambda e: e["baseLayer"].__setitem__("animations", [_scalar_group(1, 1)]), "always empty", id="r3-a-root-with-animations",
        ),
        pytest.param(lambda e: e.__setitem__("type", "somethingElse"), "type", id="r3-a-type-outside-transition-or-buildIn"),
        # Round 4 item 3: `math.isfinite` raises `OverflowError` (not `False`) on a Python int too
        # large to convert to a float; the validator must catch that itself, not rely on the net.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["initialState"].__setitem__("width", 10**400),
            "finite number", id="r4-item3-huge-integer-width-not-overflowerror",
        ),
        # Round 4 item 4 (Fable B2): zPosition bound.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["animations"][0]["animations"].append(_scalar_group(0, 2, "zPosition")["animations"][0]),
            "range", id="r4-B2-zPosition-scalar-exceeding-the-measured-bound",
        ),
        # Round 4 (Fable S1): removedOnCompletion is pinned, not merely boolean-typed.
        pytest.param(
            lambda e: e["baseLayer"]["layers"][4]["animations"][0].__setitem__("removedOnCompletion", True),
            "removedOnCompletion", id="r4-S1-group-removedOnCompletion-must-be-false",
        ),
        pytest.param(
            lambda e: _leaf_animation(e, 4).__setitem__("removedOnCompletion", False),
            "removedOnCompletion", id="r4-S1-leaf-removedOnCompletion-must-be-true",
        ),
    ],
)
def test_the_effect_schema_refuses(mutate, match):
    effect = _mutate_sanitized_effect(mutate)
    with pytest.raises(_Refuse, match=match):
        _check_effect_encoding(effect)
    assert isinstance(effect_opacity_overrides(effect), Unsupported)


@pytest.mark.parametrize("bad_points", ["bad", [1, 2], [[1, 2, 3]], [[1, "x"]], [[1, 2], [3, 4]]])
def test_shape_path_points_must_be_a_single_finite_pair(bad_points):
    def tamper(effect):
        _slot_leaf(effect, 4)["texturedRectangle"]["shapePath"]["elements"][0]["points"] = bad_points

    with pytest.raises(_Refuse, match="points"):
        _check_effect_encoding(_mutate_sanitized_effect(tamper))


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda leaf: leaf["initialState"].__setitem__("hidden", True), "hidden"),
        (lambda leaf: leaf["initialState"].__setitem__("masksToBounds", True), "masksToBounds"),
        (lambda leaf: leaf["initialState"]["contentsRect"].__setitem__("width", 0.5), "contentsRect"),
    ],
)
def test_rendering_sensitive_neutrals_are_pinned_to_their_measured_value(mutate, match):
    def tamper(effect):
        mutate(_slot_leaf(effect, 0))

    with pytest.raises(_Refuse, match=match):
        _check_effect_encoding(_mutate_sanitized_effect(tamper))


# --- geometry, settlement and fail-closed refusals: `effect_opacity_overrides` is Unsupported ---


@pytest.mark.parametrize(
    "mutate, reason",
    [
        # Codex round 3 item A's last sentence: even a malformed input the specific validators did
        # not anticipate must come back `Unsupported`, never propagate a raw exception.
        pytest.param(
            lambda e: e["baseLayer"].__setitem__("layers", None),
            "<transition effect>.baseLayer.layers is not a readable list", id="r3A-layers-none-is-unsupported-not-an-exception",
        ),
        # Slot 3's leaf has neither an opacity animation nor (after this) a readable
        # `initialState.opacity`; the old code silently defaulted to 1.0 -- it must now refuse.
        pytest.param(
            lambda e: _slot_leaf(e, 3)["initialState"].pop("opacity"), "opacity", id="missing-opacity-without-a-settled-animation",
        ),
        # Finding 4 (round 2): the rect formula's geometry invariants are validated, not assumed.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["initialState"].__setitem__("anchorPoint", {"pointX": 0.2, "pointY": 0.5}),
            "accumulated geometry error", id="r2-finding4-off-center-anchor-point",
        ),
        pytest.param(
            lambda e: e["baseLayer"]["layers"][4]["initialState"].__setitem__("rotation", 90), "rotated", id="r2-finding4-rotated-wrapper",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 4)["initialState"].__setitem__("affineTransform", [1, 0.3, 0, 1, 0, 0]),
            "affineTransform", id="r2-finding4-non-identity-affine-transform",
        ),
        pytest.param(
            lambda e: e["baseLayer"]["layers"][4]["initialState"].__setitem__("scale", 2), "scale", id="r2-finding4-non-unit-initialState-scale",
        ),
        pytest.param(_skew_leaf_sublayer_transform, "sublayerTransform", id="r2-finding4-non-identity-sublayerTransform"),
        # The formula never reads a leaf's `position` (it derives the leaf centre from the
        # wrapper's position plus the leaf's own translation animation), so moving it must be
        # caught by the centred-in-parent invariant, not silently ignored.
        pytest.param(
            lambda e: _nudge_x(_slot_leaf(e, 4)["initialState"], 100), "accumulated geometry error", id="r2-finding4-leaf-position-moved-100px",
        ),
        pytest.param(_add_wrapper_translation, "on a non-leaf node", id="r2-finding4-wrapper-translation-animation"),
        # Codex round 3 item B: root position-anchor composition, positive scale, total post-scale
        # anchor-error bound rather than a per-node pre-scale bound.
        # The plan section 0 measurement: `root.position - root.anchorPoint * root.size == (0, 0)`
        # exactly on the qualified boundary. The formula reads every wrapper's `position` as an
        # absolute canvas coordinate, which is only true when the root sits flush at the origin.
        pytest.param(
            lambda e: _nudge_x(e["baseLayer"]["initialState"], 100), "accumulated geometry error", id="r3B-root-position-moved-100px",
        ),
        pytest.param(_negate_slot4_scale_x, "non-positive settled leaf scale", id="r3B-negative-settled-scale"),
        # Slot 4 scales ~1.98x; an anchor deviation of 0.003 at its unscaled width (178px) is a
        # 0.53px error -- under a PER-NODE pre-scale 1px bound, which is exactly why round 2's
        # fixed-tolerance check was insufficient. After the ~1.98x settled scale the same deviation
        # is a ~1.06px error on the FINAL rendered rect edge, over the plan's 1px contract.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["initialState"].__setitem__("anchorPoint", {"pointX": 0.503, "pointY": 0.5}),
            "accumulated geometry error", id="r3B-near-limit-anchor-error-only-exceeds-1px-after-scaling",
        ),
        # Codex round 3 item C (SHOULD-FIX); see also test_an_overflowed_rect_component_refuses.
        pytest.param(
            _set_slot4_settled_scale(lambda _anim: 1e308, centre_the_anchor=True),
            "non-finite emitted rect", id="r3C-overflowed-rect-with-zero-anchor-error-refuses-on-finiteness",
        ),
        # The fixture has at most one `opacity` animation per node; a second is unmeasured. Which
        # one the runtime's own "last" rule (list order vs. begin-time order) would pick if they
        # disagree is exactly the ambiguity the plan's fail-closed rule exists to refuse.
        pytest.param(
            lambda e: _slot_leaf(e, 4).__setitem__(
                "animations", [_scalar_group(0.9, 0.9), _scalar_group(REAL_SLOT4_OPACITY, REAL_SLOT4_OPACITY)]
            ),
            "more than one settled opacity animation", id="r3C-more-than-one-settled-opacity-animation-on-one-node",
        ),
        # Round 4 item 1: discriminated wrapper/leaf schemas. A top-level slot must be a
        # non-textured wrapper with at least one child; substituting slot 4's own leaf in its place
        # used to pass the old schema and emit an override with the WRONG rect.
        pytest.param(
            lambda e: e["baseLayer"]["layers"].__setitem__(4, _slot_leaf(e, 4)),
            "<transition effect>.baseLayer.layers[4] carries unmeasured keys ['texture', 'texturedRectangle']",
            id="r4-item1-a-wrapper-replaced-by-its-own-leaf",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 4).pop("texture"),
            "<transition effect>.baseLayer.layers[4].layers[0] is missing measured keys ['texture']",
            id="r4-item1-a-leaf-without-texture",
        ),
        pytest.param(
            lambda e: _slot_leaf(e, 4).pop("texturedRectangle"),
            "<transition effect>.baseLayer.layers[4].layers[0] is missing measured keys ['texturedRectangle']",
            id="r4-item1-a-leaf-without-texturedRectangle",
        ),
        pytest.param(
            _wrapper_gains_its_leafs_texture,
            "<transition effect>.baseLayer.layers[4] carries unmeasured keys ['texture', 'texturedRectangle']",
            id="r4-item1-a-wrapper-carrying-texture-keys",
        ),
        # Round 4 item 2: one per-axis <=1px geometry budget, not independent per-check budgets.
        # 0.75px root-origin residual plus 0.75px child-position residual is 1.5px of real,
        # ignored displacement even though EACH alone is under the old independent 1px budgets.
        pytest.param(
            lambda e: (_nudge_x(e["baseLayer"]["initialState"], 0.75), _nudge_x(_slot_leaf(e, 4)["initialState"], 0.75)),
            "accumulated geometry error", id="r4-item2-root-and-child-subpixel-residuals-combine",
        ),
        pytest.param(_negative_wrapper_width, "non-positive", id="r4-item2-negative-wrapper-size-with-a-consistent-child-position"),
        # Round 4 item 3: numeric overflow and the fail-closed net.
        pytest.param(
            lambda e: e.__setitem__("duration", 10**1000),
            "<transition effect>.duration is not a readable finite number", id="r4-item3-huge-integer-duration-not-overflowerror",
        ),
        # Round 4 item 4 (Fable B2): sublayerTransform off identity.
        pytest.param(
            lambda e: e["baseLayer"]["layers"][0]["initialState"]["sublayerTransform"].__setitem__(0, 1.0019),
            "non-identity sublayerTransform", id="r4-B2-sublayerTransform-index-0-off-identity",
        ),
        pytest.param(
            lambda e: e["baseLayer"]["layers"][4]["initialState"]["sublayerTransform"].__setitem__(3, 0.002),
            "non-identity sublayerTransform", id="r4-B2-sublayerTransform-index-3-perspective-off-identity",
        ),
    ],
)
def test_effect_opacity_overrides_refuses(mutate, reason):
    result = effect_opacity_overrides(_mutate_sanitized_effect(mutate))
    assert isinstance(result, Unsupported)
    assert reason in result.reason


@pytest.mark.parametrize(
    "mutate",
    [
        # slot 4's leaf carries three leaf animations, one of which naturally lacks
        # `timingFunction` (measured on the real export: 15 of 16 leaves have it), so the optional
        # key is accepted when genuinely absent.
        pytest.param(lambda e: _leaf_animation(e, 4).pop("timingFunction"), id="r3A-an-absent-timingFunction"),
        pytest.param(lambda e: e.__setitem__("type", "buildIn"), id="r3-buildIn-type"),
        # Slot 0 (background, 1920px wide, scale exactly 1) tolerates a deviation that would sink
        # a scaled, narrower slot: 0.0003 * 1920px = 0.576px, under the 1px contract with no scale
        # involved -- proving the post-scale bound is not simply stricter across the board.
        pytest.param(
            lambda e: _slot_leaf(e, 0)["initialState"].__setitem__("anchorPoint", {"pointX": 0.5 + 0.0003, "pointY": 0.5}),
            id="r3B-a-small-anchor-deviation-on-an-unscaled-slot",
        ),
        pytest.param(
            lambda e: e["baseLayer"]["layers"][0]["initialState"]["sublayerTransform"].__setitem__(11, -0.0004),
            id="r4-B2-sublayerTransform-index-11-at-the-measured-value",
        ),
    ],
)
def test_a_measured_variation_is_accepted(mutate):
    effect = _mutate_sanitized_effect(mutate)
    _check_effect_encoding(effect)
    assert isinstance(effect_opacity_overrides(effect), dict)


@pytest.mark.parametrize(
    "mutate, slot, reason",
    [
        # The old `abs(from - to) > 1e-9` rule let a 1e-12 drift through as 'settled'; the plan's
        # `from != to` is exact, so even a float-noise-sized difference must exclude.
        pytest.param(
            lambda e: e["baseLayer"]["layers"][0].__setitem__("animations", [_scalar_group(1.0, 1.0 + 1e-12)]),
            0, "fade", id="fade-uses-exact-inequality-not-a-tolerance",
        ),
        pytest.param(_add_slot3_hidden_animation, 3, "hidden", id="hidden-presence-excludes-regardless-of-settlement"),
        pytest.param(_drop_slot1_hidden_animation, 1, "fade", id="a-faded-slot-is-excluded-not-refused"),
        # Codex round 3 item C (SHOULD-FIX).
        pytest.param(_three_factor_nan_product, 0, "product-mismatch", id="r3C-a-real-three-factor-nan-product"),
        pytest.param(_two_factor_overflow_product, 0, "product-mismatch", id="r3C-an-overflow-to-infinity-product"),
        # O1's own candidate rule: the settled product must equal `singleTextureOpacity`.
        pytest.param(
            lambda e: _slot_leaf(e, 4)["texturedRectangle"].__setitem__("singleTextureOpacity", 0.5),
            4, "product-mismatch", id="settled-product-must-equal-singleTextureOpacity",
        ),
    ],
)
def test_a_slot_is_excluded_not_overridden(mutate, slot, reason):
    result = effect_opacity_overrides(_mutate_sanitized_effect(mutate))
    assert isinstance(result, dict)
    assert {"slot": slot, "reason": reason} in result["excluded"]
    assert all(o["slot"] != slot for o in result["opacityOverrides"])


def test_an_overflowed_rect_component_refuses():
    result = effect_opacity_overrides(_mutate_sanitized_effect(_set_slot4_settled_scale(lambda _anim: 1e300)))
    assert isinstance(result, Unsupported)
    # a 1e300 scale first exceeds the accumulated 1px geometry-error contract (an anchor
    # deviation that was negligible unscaled becomes enormous), which is itself the correct
    # fail-closed outcome for ungoverned scale growth; the finite-rect check is the backstop for
    # the remaining case where anchor error is exactly zero and the rect components alone go
    # non-finite.
    assert "accumulated geometry error" in result.reason or "non-finite emitted rect" in result.reason


def test_multi_node_product_uses_a_non_one_initial_state_opacity_fallback():
    """Neither the wrapper nor the leaf of slot 3 has an opacity animation; give both a non-1,
    non-default `initialState.opacity` whose product still equals the (mutated)
    `singleTextureOpacity`, isolating the multi-node initialState-fallback path (as opposed to
    the settled-animation path every other test exercises)."""

    def non_one_initial_opacities(effect):
        wrapper_state = effect["baseLayer"]["layers"][3]["initialState"]
        leaf = _slot_leaf(effect, 3)
        wrapper_state["opacity"] = 0.5
        leaf["initialState"]["opacity"] = 0.6
        leaf["texturedRectangle"]["singleTextureOpacity"] = 0.3

    result = effect_opacity_overrides(_mutate_sanitized_effect(non_one_initial_opacities))
    assert isinstance(result, dict)
    assert not any(e["slot"] == 3 for e in result["excluded"])
    override = next(o for o in result["opacityOverrides"] if o["slot"] == 3)
    assert override["opacity"] == pytest.approx(0.3, abs=1e-9)


def _wrapper_shell(width: float, height: float, position: tuple[float, float]) -> dict:
    return {
        "animations": [],
        "initialState": {
            "affineTransform": [1, 0, 0, 1, 0, 0], "anchorPoint": {"pointX": 0.5, "pointY": 0.5},
            "contentsRect": {"x": 0, "y": 0, "width": 1, "height": 1}, "edgeAntialiasingMask": 0,
            "height": height, "hidden": False, "masksToBounds": False, "opacity": 1,
            "position": {"pointX": position[0], "pointY": position[1]}, "rotation": 0, "scale": 1,
            "sublayerTransform": list(_IDENTITY_SUBLAYER_TRANSFORM), "width": width,
        },
        "layers": [],
    }


def test_a_very_deep_layers_chain_refuses_via_the_recursion_guard():
    """Round 4 item 3. 600 genuine wrapper levels (no leaf shape at any intermediate level, so the
    wrapper/leaf schema does not short-circuit this early for an unrelated reason) exceed
    Python's default recursion limit inside the recursive schema validator; the public net's
    broadened `except Exception` catches the resulting `RecursionError`. This is a deliberate
    choice over an explicit depth cap in the schema: no measured deck approaches this depth, and
    the recursion limit is a real, already-enforced backstop for it."""

    def very_deep_chain(effect):
        wrapper = effect["baseLayer"]["layers"][4]
        width, height = wrapper["initialState"]["width"], wrapper["initialState"]["height"]
        real_leaf = copy.deepcopy(_leaf_of(wrapper))
        node = _wrapper_shell(width, height, (width / 2, height / 2))
        top = node
        for _ in range(600):
            child = _wrapper_shell(width, height, (width / 2, height / 2))
            node["layers"] = [child]
            node = child
        node["layers"] = [real_leaf]
        wrapper["layers"] = [top]

    result = effect_opacity_overrides(_mutate_sanitized_effect(very_deep_chain))
    assert isinstance(result, Unsupported)
    assert result.reason.startswith("unexpected malformed input")


def test_the_fail_closed_net_is_exercised_by_a_monkeypatched_exception(monkeypatch):
    """`layers=None`-style mutations are refused by the schema itself, which never reaches the
    net -- deleting the net's `except` clause would not fail that test. Monkeypatch the inner
    implementation to raise something only the net's `except Exception` catches, and assert the
    public function converts it rather than propagating it."""
    from obed_edom import live_continuity

    def boom(effect):
        raise ZeroDivisionError("simulated non-_Refuse failure")

    monkeypatch.setattr(live_continuity, "_effect_opacity_overrides", boom)
    result = effect_opacity_overrides(_sanitized_effect())
    assert isinstance(result, Unsupported)
    assert result.reason.startswith("unexpected malformed input")
    assert "ZeroDivisionError" in result.reason


def test_duplicate_size_only_blocks_patched_slots():
    def duplicate_among_full_opacity_slots(effect):
        source = _leaf_of(effect["baseLayer"]["layers"][0])
        target = _leaf_of(effect["baseLayer"]["layers"][2])
        target["initialState"]["width"] = source["initialState"]["width"]
        target["initialState"]["height"] = source["initialState"]["height"]
        target["initialState"]["anchorPoint"] = {"pointX": 0.5, "pointY": 0.5}

    harmless = effect_opacity_overrides(_mutate_sanitized_effect(duplicate_among_full_opacity_slots))
    assert isinstance(harmless, dict)
    assert harmless["opacityOverrides"] == [
        {"slot": 4, "opacity": REAL_SLOT4_OPACITY, "texW": 178, "texH": 157}
    ]
    assert not any(e["reason"] == "duplicate-size" for e in harmless["excluded"])

    def duplicate_onto_the_patched_slot(effect):
        target = _leaf_of(effect["baseLayer"]["layers"][1])
        target["initialState"]["width"] = 178
        target["initialState"]["height"] = 157

    blocked = effect_opacity_overrides(_mutate_sanitized_effect(duplicate_onto_the_patched_slot))
    assert isinstance(blocked, dict)
    assert blocked["opacityOverrides"] == []
    assert {"slot": 4, "reason": "duplicate-size"} in blocked["excluded"]


# --- the one real-export parity test: sanitized fixture == real export, other effects classified
# --- by measured shape ---------------------------------------------------------------------


def _real_export_effects(root: Path = REAL_PLAYER_ROOT) -> list[tuple[str, int, int, dict]]:
    slide_list = json.loads((root / "assets" / "header.json").read_text())["slideList"]
    found = []
    for uuid in slide_list:
        data = json.loads((root / "assets" / uuid / f"{uuid}.json").read_text())
        for event_index, event in enumerate(data["events"]):
            for effect_index, effect in enumerate(event.get("effects", [])):
                found.append((uuid, event_index, effect_index, effect))
    return found


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_matches_fixture_and_classifies_other_effects_by_shape():
    slide_list = json.loads((REAL_PLAYER_ROOT / "assets" / "header.json").read_text())["slideList"]
    data = json.loads(
        (REAL_PLAYER_ROOT / "assets" / slide_list[0] / f"{slide_list[0]}.json").read_text()
    )
    real_effect = data["events"][1]["effects"][0]

    real_result = effect_opacity_overrides(real_effect)
    _assert_is_the_qualified_1_to_2_result(real_result)
    assert real_result == effect_opacity_overrides(_sanitized_effect())

    # Other effects are classified by their measured shape: `apple:movie-start` build-ins fail
    # the closed `fillMode` set (they use `removed`, never measured for this boundary),
    # `apple:dissolve character` build-ins fail the pinned `initialState.hidden == False`
    # invariant (they genuinely animate visibility), and the export's OTHER plain
    # `apple:dissolve` transitions author leaf animations directly under a layer-node's
    # `animations` (no group wrapper), which the group/leaf nesting schema now refuses -- only
    # the export's second magic-move transition (slide 3->4) shares this boundary's exact
    # structure and correctly passes.
    for uuid, event_index, effect_index, other in _real_export_effects():
        if (uuid, event_index, effect_index) == (slide_list[0], 1, 0):
            continue
        name = other.get("name")
        kind = other.get("type")
        if kind == "buildIn" and name == "apple:movie-start":
            with pytest.raises(_Refuse, match="fillMode"):
                _check_effect_encoding(other)
        elif kind == "buildIn" and name == "apple:dissolve character":
            with pytest.raises(_Refuse, match="hidden"):
                _check_effect_encoding(other)
        elif kind == "transition" and name == "apple:dissolve":
            with pytest.raises(_Refuse, match="unmeasured keys"):
                _check_effect_encoding(other)
        else:
            _check_effect_encoding(other)


# --- G1: glReplay derivation (arming plan section 11) ---------------------------------------

GL_REPLAY_RUNTIME_PLAN_SHA256 = "2fbf977277a5eef1cde701c12bb157905e40ac2b0a5ed85e30bf1056a3e65c18"

# `derive_plan(..., gl_replay=True)` on the fixture must produce exactly the schema-2 contract.
EXPECTED_GL_REPLAY_RUNTIME_PLAN = RUNTIME_V2_EXAMPLES["p2_gl"]


def test_gl_replay_defaults_to_off_and_is_byte_identical_to_today():
    plan_default = _plan()
    plan_off = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=False)
    assert isinstance(plan_default, ContinuityPlan)
    assert isinstance(plan_off, ContinuityPlan)
    runtime_default = plan_default.to_runtime()
    runtime_off = plan_off.to_runtime()
    assert runtime_default == EXPECTED_RUNTIME_PLAN
    assert runtime_off == EXPECTED_RUNTIME_PLAN
    from obed_edom import live_continuity

    assert live_continuity.plan_signature(runtime_off) == EXPECTED_PLAN_SHA256
    for boundary in plan_off.boundaries:
        for movie in boundary.movies:
            assert movie.gl_replay is None
            assert movie.gl_replay_reason is None


def test_gl_replay_flag_on_derives_the_slot4_override():
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    boundary = _boundary(plan, 0)
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert movies["untitled.mov"]["action"] == "pin"
    assert movies["untitled.mov"]["glReplay"] is True
    assert movies["untitled.mov"]["glReplayReason"] is None

    refusal = next(r for r in plan.refusals if r["atScene"] == 2)
    assert refusal["glReplay"] is True
    assert refusal["glReplayReason"] is None
    assert refusal["opacityExcluded"] == [{"slot": 1, "reason": "fade"}]


def test_gl_replay_flag_on_runtime_plan_is_pinned_and_qualified():
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    for got, want in zip(
        runtime["boundaries"][0]["slotRects"], EXPECTED_GL_REPLAY_RUNTIME_PLAN["boundaries"][0]["slotRects"]
    ):
        for g, w in zip(got, want):
            assert g == pytest.approx(w, abs=5e-3)
    trimmed = json.loads(json.dumps(runtime))
    trimmed["boundaries"][0]["slotRects"] = EXPECTED_GL_REPLAY_RUNTIME_PLAN["boundaries"][0]["slotRects"]
    assert trimmed == EXPECTED_GL_REPLAY_RUNTIME_PLAN

    from obed_edom import live_continuity

    assert live_continuity.plan_signature(runtime) == GL_REPLAY_RUNTIME_PLAN_SHA256
    assert GL_REPLAY_RUNTIME_PLAN_SHA256 in live_continuity.QUALIFIED_PLAN_SHA256


def _add_second_continuing_movie(tmp: Path) -> None:
    """Give the 0->1 boundary a second continuing asset, alongside 'untitled.mov', so
    `len(continuing) != 1` (rule 2). The clone is a deep copy of the qualified movie node with a
    new asset id and object id, discoverable by `_find_movie_nodes`'s generic recursion and given
    its own draw slot on slide 2 so the (unrelated) overlap check it also triggers does not raise."""

    def clone_onto_slide1(data):
        events = copy.deepcopy(data["events"])
        source = _find_movie_nodes(events)[0]
        clone = copy.deepcopy(source)
        clone["objectID"] = "CLONE-SECOND-MOVIE"
        clone["movie"] = {**clone["movie"], "asset": "Second.mov-0.0000-1.0"}
        events[0]["clonedMovies"] = [clone]
        data = {**data, "events": events}
        data = {
            **data,
            "assets": {
                **data["assets"],
                "Second.mov-0.0000-1.0": {
                    "type": "video", "url": {"web": "assets/Second.mov-0.0000-1.0.mov"},
                },
            },
        }
        return data

    def clone_onto_slide2(data):
        events = copy.deepcopy(data["events"])
        source = _find_movie_nodes(events)[0]
        clone = copy.deepcopy(source)
        clone["objectID"] = "CLONE-SECOND-MOVIE-2"
        clone["movie"] = {**clone["movie"], "asset": "Second.mov-0.0000-1.0"}
        events[0]["clonedMovies"] = [clone]
        events[0]["baseLayer"]["layers"].insert(0, {"layers": [{"objectID": "CLONE-SECOND-MOVIE-2"}]})
        data = {**data, "events": events}
        data = {
            **data,
            "assets": {
                **data["assets"],
                "Second.mov-0.0000-1.0": {
                    "type": "video", "url": {"web": "assets/Second.mov-0.0000-1.0.mov"},
                },
            },
        }
        return data

    _rewrite_slide_json(tmp, SLIDE1, clone_onto_slide1)
    _rewrite_slide_json(tmp, SLIDE2, clone_onto_slide2)


def test_gl_replay_rule2_rejects_more_than_one_continuing_movie():
    tmp = _copy_fixture_tree()
    _add_second_continuing_movie(tmp)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    refusal = next(r for r in plan.refusals if r["atScene"] == 2 and r["asset"] == "untitled.mov")
    assert refusal["glReplay"] is False
    assert "movies are carried across the boundary, expected exactly 1" in refusal["glReplayReason"]
    assert refusal["glReplayReason"].startswith("2 movies")
    # the clone is itself refused too (it is drawn under the other authored artwork), so the
    # boundary retires both instances, each on its own entry.
    assert sorted((r["asset"], r["code"]) for r in plan.refusals if r["atScene"] == 2) == [
        ("second.mov", "overlap"), ("untitled.mov", "overlap"),
    ]


def _map_transitions_effect(data, transform):
    """Like `_map_transitions`, but hands the whole transition-effect dict (not just its
    `name`) to `transform`, for the rule-5 mutation tests."""
    events = copy.deepcopy(data["events"])

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "transition":
                transform(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(events)
    return {**data, "events": events}


def _set_first_event_automatic_play(automatic_play):
    def apply(data):
        events = copy.deepcopy(data["events"])
        if automatic_play == "popped":
            events[0].pop("automaticPlay")
        else:
            events[0]["automaticPlay"] = automatic_play
        return {**data, "events": events}

    return apply


@pytest.mark.parametrize(
    "uuid, transform, reason",
    [
        pytest.param(
            SLIDE1, lambda data: _map_transitions(data, lambda _name: "apple:magic-move-dissolve"),
            "transition 'apple:magic-move-dissolve' is not in the measured WebGL list", id="rule1-an-unmeasured-transition-name",
        ),
        *[
            pytest.param(
                SLIDE2, _set_first_event_automatic_play(value),
                f"destination first event is not click-driven (automaticPlay={None if value == 'popped' else value!r})",
                id=f"rule4-a-non-click-driven-destination-{value}",
            )
            for value in (True, "popped", 1)
        ],
        pytest.param(
            SLIDE1, lambda data: _map_transitions_effect(data, lambda effect: effect.pop("attributes")),
            "transition effect: <transition effect> is missing measured keys ['attributes']",
            id="rule5-a-missing-effect-attributes-key",
        ),
        pytest.param(
            SLIDE1,
            lambda data: _map_transitions_effect(
                data,
                lambda effect: _slot_leaf(effect, 4)["animations"][0]["animations"][0].__setitem__("property", "transform.rotation.z"),
            ),
            "transition effect: <transition effect>.baseLayer.layers[4].layers[0].animations[0].animations[0].property "
            "is not a measured property",
            id="rule5-an-unmeasured-animation-property",
        ),
    ],
)
def test_gl_replay_rule_failure_falls_back_to_the_qualified_retire(uuid, transform, reason):
    plan = derive_plan(_mutate_slide(uuid, transform), SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    refusal = next(r for r in plan.refusals if r["atScene"] == 2)
    assert refusal["glReplay"] is False
    assert refusal["glReplayReason"] == reason
    boundary_movies = {m["asset"]: m for m in _boundary(plan, 0)["movies"]}
    assert boundary_movies["untitled.mov"]["glReplayReason"] == reason
    # a failed arming rule falls back to the ordinary (already-qualified) retire boundary.
    assert plan.to_runtime() == EXPECTED_RUNTIME_PLAN


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(lambda gl_replay: {**gl_replay, "opacityOverrides": "not-a-list"}, id="overrides-not-a-list"),
        pytest.param(lambda gl_replay: {**gl_replay, "slotRects": gl_replay["slotRects"][:-1]}, id="mismatched-slot-lists"),
    ],
)
def test_to_runtime_refuses_an_unreadable_gl_replay_override_table(corrupt):
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].movies[0]
    assert movie.gl_replay is not None
    result = _gl_replay_plan_with(gl_replay=corrupt(movie.gl_replay)).to_runtime()
    assert isinstance(result, Unsupported)
    assert "unreadable override table" in result.reason


# --- G1b: instanceId / instanceRect / movieSlot (G2 plan section 2.0) -----------------------


def _gl_replay_plan_with(**movie_fields) -> ContinuityPlan:
    """The flag-on fixture plan with the carried movie's G1b inputs overridden."""
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    boundary = plan.boundaries[0]
    movie = boundary.movies[0]
    assert movie.gl_replay is not None
    bad_boundary = replace(boundary, movies=(replace(movie, **movie_fields),))
    return replace(plan, boundaries=(bad_boundary, *plan.boundaries[1:]))


def test_gl_replay_entry_binds_the_probe_instance_label_rect_and_slot():
    """The three G1b fields must be exactly what the probe binds: `asset#index` over the
    DOM-ordered `slide_instances` list, that list's stored floats verbatim, and the movie's
    index in `slotSizes`/`slotRects`."""
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    entry = runtime["boundaries"][0]

    asset = runtime["movies"][entry["movieKey"]]["assetKeys"][0]
    destination = plan.slide_instances[1][asset]
    assert entry["instanceId"] == f"{asset}#1"
    assert entry["instanceRect"] == destination[0]
    assert entry["instanceRect"] is not destination[0]
    assert entry["movieSlot"] == 3
    assert entry["slotSizes"][entry["movieSlot"]] == [960, 276]
    assert list(entry)[-3:] == ["instanceId", "instanceRect", "movieSlot"]


def test_movie_slot_agrees_across_every_source_event_that_draws_the_movie():
    """Codex r1 spec 3. `slotSizes`/`slotRects` come from the qualifying transition effect and
    `movieSlot` indexes them positionally, so a source event whose draw order puts the movie
    somewhere else would make the index address the wrong slot. The transition's own layers carry
    no `objectID` (every slot's child has `objectID is None` on the fixture), so the index cannot
    be read from the transition directly; instead every source event that draws the movie must
    agree, and a disagreement refuses the boundary rather than picking the first match."""
    from obed_edom.live_continuity import _draw_slots, _drawn_slot_index, _Refuse

    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].movies[0]
    assert movie.gl_replay_slot == 3
    slot_count = len(movie.gl_replay["slotSizes"])

    instance = _MovieInstanceStub(object_id="movie-object")
    def event(order):
        return {"baseLayer": {"layers": [{"layers": [{"objectID": name}]} for name in order]}}

    names = [f"other{i}" for i in range(slot_count)]
    agreeing = list(names)
    agreeing[3] = "movie-object"
    assert _drawn_slot_index([event(agreeing), event(agreeing)], instance, "s1", slot_count) == 3

    reordered = list(names)
    reordered[1] = "movie-object"
    with pytest.raises(_Refuse, match="slot 3 and slot 1"):
        _drawn_slot_index([event(agreeing), event(reordered)], instance, "s1", slot_count)

    short = ["movie-object", *names[:2]]
    with pytest.raises(_Refuse, match="draws 3 slots where the boundary transition has 5"):
        _drawn_slot_index([event(short)], instance, "s1", slot_count)



class _MovieInstanceStub:
    def __init__(self, object_id):
        self.object_id = object_id


def test_gl_replay_instance_rect_selects_exactly_one_source_slide_instance():
    """G3 plan section 2, the offline half of instance selection. The core binds the carried
    decoder by matching each pooled source decoder's authored rect against `instanceRect` within
    1.0 px per edge, with no size-only or only-candidate fallback. On the flag-on fixture exactly
    one slide-1 instance of the carried asset may match: the big instance (equal to the
    destination rect, since the pin pair is byte-exact), never the 966 px-away sibling."""
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    entry = next(b for b in runtime["boundaries"] if b["action"] == "glReplay")
    asset = runtime["movies"][entry["movieKey"]]["assetKeys"][0]
    target = entry["instanceRect"]
    source_player = next(b.from_player_index for b in plan.boundaries if b.movies and b.movies[0].gl_replay)
    source = plan.slide_instances[source_player][asset]

    def within(rect, target_rect, tolerance=1.0):
        return all(abs(rect[edge] - target_rect[edge]) <= tolerance for edge in ("x", "y", "w", "h"))

    assert len(source) == 2
    matches = [rect for rect in source if within(rect, target)]
    assert len(matches) == 1
    assert matches[0] == target
    sibling = next(rect for rect in source if rect is not matches[0])
    assert abs(sibling["x"] - target["x"]) > 900


@pytest.mark.parametrize("slot", [None, 5, -1, True, 3.0])
def test_to_runtime_refuses_an_out_of_range_or_unreadable_movie_slot(slot):
    result = _gl_replay_plan_with(gl_replay_slot=slot).to_runtime()
    assert isinstance(result, Unsupported)
    assert "no readable movie slot index" in result.reason


def test_to_runtime_refuses_a_non_finite_instance_rect():
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    boundary = plan.boundaries[0]
    movie = boundary.movies[0]
    assert movie.dst_rect is not None
    infinite = Rect(movie.dst_rect.x, movie.dst_rect.y, movie.dst_rect.w, float("inf"))
    bad_boundary = replace(boundary, movies=(replace(movie, dst_rect=infinite),))
    instances = {
        player: {asset: [dict(r) for r in rects] for asset, rects in by_asset.items()}
        for player, by_asset in plan.slide_instances.items()
    }
    instances[1]["untitled.mov"][0]["h"] = float("inf")
    result = replace(
        plan, boundaries=(bad_boundary, *plan.boundaries[1:]), slide_instances=instances
    ).to_runtime()
    assert result == Unsupported("pin of 'untitled.mov' at scene 2 does not name its destination instance")


def test_to_runtime_refuses_when_the_destination_instance_is_not_in_slide_instances():
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    instances = {player: dict(by_asset) for player, by_asset in plan.slide_instances.items()}
    instances[1] = {}
    result = replace(plan, slide_instances=instances).to_runtime()
    assert isinstance(result, Unsupported)
    assert "not in slide_instances" in result.reason


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_gl_replay_parity_both_flag_states():
    for flag in (False, True):
        real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=_unchecked_resolver, gl_replay=flag)
        fixture = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=flag)
        assert isinstance(real, ContinuityPlan)
        assert isinstance(fixture, ContinuityPlan)
        assert real.to_runtime() == fixture.to_runtime()
        assert real.refusals == fixture.refusals


# --- Codex round 1 findings ------------------------------------------------------------------


def test_flag_off_as_dict_and_json_have_no_gl_replay_keys():
    """Finding 1 (High): flag-off serialization must be byte-identical to pre-G1 -- no
    `glReplay`/`glReplayReason`/`opacityExcluded` key anywhere in `as_dict()` or `to_json()`,
    including on the refusal record and every `MovieContinuity.as_dict()`."""
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=False)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals  # the boundary still refuses; only the new keys must be absent
    as_dict = plan.as_dict()
    dumped = json.dumps(as_dict)
    assert "glReplay" not in dumped
    assert "glReplayReason" not in dumped
    assert "opacityExcluded" not in dumped
    assert plan.to_json() == json.dumps(as_dict)
    for boundary in as_dict["boundaries"]:
        for movie in boundary["movies"]:
            assert set(movie) - {"code"} == {
                "asset", "action", "srcRect", "dstRect", "srcObjectId", "dstObjectId", "loop",
            }
    for refusal in as_dict["refusals"]:
        assert set(refusal) == {
            "fromPlayer", "toPlayer", "atScene", "asset", "movieKey", "reason", "code", "objectId",
        }


@pytest.mark.parametrize("bad_name", [42, [1, 2], {"nested": "object"}])
def test_gl_replay_rejects_unreadable_transition_name_instead_of_raising(bad_name):
    """Finding 2 (Medium): a JSON-valid non-string transition `name` must not raise at
    `.startswith()` or at the `_GL_REPLAY_TRANSITIONS` membership test (an unhashable `list`/
    `dict` raises `TypeError` there) -- it must fail closed to `Unsupported`."""
    tmp = _mutate_slide(SLIDE1, lambda data: _map_transitions(data, lambda _name: bad_name))
    plan = derive_plan(tmp, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, Unsupported)
    assert "unreadable transition name" in plan.reason

    plan_off = derive_plan(tmp, SLIDES, resolver=_resolver, gl_replay=False)
    assert isinstance(plan_off, Unsupported)
    assert "unreadable transition name" in plan_off.reason


# --- looping movies: `movie.loopMode` (keynote_live_continuity_loopmode plan section 2) -----
#
# Keynote's Repeat -> Loop writes exactly one key, `movie.loopMode: "looping"`, on the
# `renderMovie` node (plan F1). The player turns it into `HTMLVideoElement.loop = true` on its
# own fresh element per slide; our runtime instead carries a decoder across a Magic Move and
# keeps the SOURCE element's `loop`. So:
#   - "looping" is the only qualified value; anything else is unmeasured vocabulary and
#     refuses the whole deck (section 2.1);
#   - a Magic Move boundary whose carried pair disagrees on loop is refused on its own (R4),
#     like an overlap; with exact instance identity only the carried pair matters
#     (generalisation plan section 2.4);
#   - every carry entry names its `loop`, so a looping deck can never reuse its non-looping
#     twin's allowlisted sha.
#
# `P2-loop` is the committed P2 fixture with the key spliced onto the same objectIDs
# `scripts/loop_fixture.py` splices (plan section 4): every `untitled.mov` instance, never
# WA0125 (`2FE5195A`).

P2_LOOP_OBJECT_IDS = (
    "6BB39942-6C61-4763-839D-777C09E7E594",  # slide 1, carried across 1->2
    "CBACAF27-B918-47C2-AB45-3ED71B6B394B",  # slide 1, the small second instance
    "F9AFED1B-E2D7-47D4-942E-14992C808383",  # slide 2
    "98D59E27-7807-477D-BEFB-27EB1CF1D185",  # slide 3, bridged 3->4
    "E4728E7D-2032-4D7F-83D6-8BE0EFB7B7BC",  # slide 4
)
P2_WA0125_OBJECT_ID = "2FE5195A-F8CF-459A-8E20-B6DF91C0047A"

# Qualified by gates L1/L2/L4/L5 on `output/fixtures/p2-loop`; re-pinned for the schema-2 runtime.
P2_LOOP_PLAN_SHA256 = "866de785864ad19b11ecd8cdfb4ad1729798ccf9f1764aa59718de03034ba7a5"
P2_LOOP_GL_REPLAY_PLAN_SHA256 = "d860a09f4f6a8e24a81e2ad0c3b37bc8a3f2b4ce3947836ca315671031870131"

NOT_YET_QUALIFIED = "deck shape is not yet qualified for continuity (only gate-measured plans are)"


def _set_loop_mode(object_ids, value):
    """A slide transform setting `movie.loopMode` on every movie node whose objectID is listed."""

    def apply(node):
        if node.get("objectID") in object_ids:
            node["movie"]["loopMode"] = value

    return lambda data: _map_movie_nodes(data, apply)


def _loop_tree(object_ids=P2_LOOP_OBJECT_IDS, value="looping", root: Path | None = None) -> Path:
    tmp = _copy_fixture_tree() if root is None else root
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        _rewrite_slide_json(tmp, uuid, _set_loop_mode(object_ids, value))
    return tmp


def test_loop_mode_is_in_the_measured_movie_vocabulary():
    from obed_edom import live_continuity

    assert "loopMode" in live_continuity._MOVIE_SUBTREE_KEYS["movie"]


def _looping(runtime: dict) -> dict:
    """`runtime` with every carry entry's `loop` set, as the looping twin derives it."""
    looped = copy.deepcopy(runtime)
    for entry in looped["boundaries"]:
        if "loop" in entry:
            entry["loop"] = True
    return looped


def test_non_looping_p2_fixture_is_unchanged_and_loops_nowhere():
    """L0-d CvC: accepting the key leaves every non-looping output where it was."""
    from obed_edom import live_continuity

    for flag, expected, sha in (
        (False, EXPECTED_RUNTIME_PLAN, EXPECTED_PLAN_SHA256),
        (True, EXPECTED_GL_REPLAY_RUNTIME_PLAN, GL_REPLAY_RUNTIME_PLAN_SHA256),
    ):
        plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=flag)
        assert isinstance(plan, ContinuityPlan)
        assert plan.loop_instances == {}
        runtime = plan.to_runtime()
        assert runtime == expected
        assert "loops" not in runtime
        assert live_continuity.plan_signature(runtime) == sha
        assert all(not movie.loop for boundary in plan.boundaries for movie in boundary.movies)


def test_p2_loop_derives_the_p2_plan_with_every_carry_looping():
    """L0-d: every `untitled.mov` instance loops, so every carried pair agrees -- the plan and its
    refusals are P2's apart from `loop`, and the runtime signs as its own allowlist entry."""
    from obed_edom import live_continuity

    plan = derive_plan(_loop_tree(), SLIDES, resolver=_resolver)
    baseline = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert isinstance(baseline, ContinuityPlan)
    assert plan.boundaries[:3] == tuple(
        replace(b, movies=tuple(replace(m, loop=True) for m in b.movies)) for b in baseline.boundaries[:3]
    )
    assert plan.boundaries[3] == baseline.boundaries[3]
    assert plan.refusals == baseline.refusals
    assert plan.loop_instances == {
        0: {"untitled.mov": [_rect(*SLIDE1_BIG), _rect(*SLIDE1_SMALL)]},
        1: {"untitled.mov": [_rect(*SLIDE1_BIG)]},
        2: {"untitled.mov": [_rect(197.98, 797.10, 951.54, 267.62)]},
        3: {"untitled.mov": [_rect(*SLIDE4_UNTITLED)]},
    }
    for player_index, assets in plan.loop_instances.items():
        assert assets["untitled.mov"] == plan.slide_instances[player_index]["untitled.mov"]
    assert "vid-20250608-wa0125.mp4" in plan.slide_instances[2]
    assert set(plan.loop_instances[2]) == {"untitled.mov"}

    runtime = plan.to_runtime()
    assert runtime == _looping(EXPECTED_RUNTIME_PLAN)
    assert live_continuity.plan_signature(runtime) == P2_LOOP_PLAN_SHA256
    assert P2_LOOP_PLAN_SHA256 in live_continuity.QUALIFIED_PLAN_SHA256
    assert P2_LOOP_PLAN_SHA256 != EXPECTED_PLAN_SHA256


def test_p2_loop_flag_on_arms_gl_replay_and_signs_its_own_sha():
    """Arming rules 1-5 are unchanged: a looping pair that agrees arms like any other, and its
    per-entry `loop` keeps its sha apart from P2's."""
    from obed_edom import live_continuity

    plan = derive_plan(_loop_tree(), SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals[0]["glReplay"] is True
    runtime = plan.to_runtime()
    assert runtime == _looping(EXPECTED_GL_REPLAY_RUNTIME_PLAN)
    assert live_continuity.plan_signature(runtime) == P2_LOOP_GL_REPLAY_PLAN_SHA256
    assert P2_LOOP_GL_REPLAY_PLAN_SHA256 in live_continuity.QUALIFIED_PLAN_SHA256
    assert P2_LOOP_GL_REPLAY_PLAN_SHA256 != GL_REPLAY_RUNTIME_PLAN_SHA256


def test_p2_loop_splice_leaves_wa0125_and_every_other_key_alone():
    """The splice is exactly F1's shape: one added key per listed node, nothing else."""
    tree = _loop_tree()
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        before = json.loads((FIXTURE_ROOT / "assets" / uuid / f"{uuid}.json").read_text())
        after = json.loads((tree / "assets" / uuid / f"{uuid}.json").read_text())
        for node in _find_movie_nodes(after["events"]):
            loop_mode = node["movie"].pop("loopMode", None)
            if node["objectID"] in P2_LOOP_OBJECT_IDS:
                assert loop_mode == "looping"
            else:
                assert node["objectID"] == P2_WA0125_OBJECT_ID
                assert loop_mode is None
        assert after == before


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_p2_export_spliced_the_same_way_signs_the_same_two_shas(tmp_path):
    """The trimmed fixture spliced must stand for the real export spliced (what
    `scripts/loop_fixture.py` builds `output/fixtures/p2-loop` from): same runtime, same shas."""
    import shutil

    from obed_edom import live_continuity

    (tmp_path / "assets").mkdir()
    shutil.copy(REAL_PLAYER_ROOT / "assets" / "header.json", tmp_path / "assets")
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        (tmp_path / "assets" / uuid).mkdir()
        shutil.copy(REAL_PLAYER_ROOT / "assets" / uuid / f"{uuid}.json", tmp_path / "assets" / uuid)
    _loop_tree(root=tmp_path)
    for flag, sha in ((False, P2_LOOP_PLAN_SHA256), (True, P2_LOOP_GL_REPLAY_PLAN_SHA256)):
        real = derive_plan(tmp_path, SLIDES, resolver=_resolver, gl_replay=flag)
        fixture = derive_plan(_loop_tree(), SLIDES, resolver=_resolver, gl_replay=flag)
        assert isinstance(real, ContinuityPlan)
        assert isinstance(fixture, ContinuityPlan)
        real_runtime = real.to_runtime()
        assert isinstance(real_runtime, dict)
        assert real_runtime == fixture.to_runtime()
        assert live_continuity.plan_signature(real_runtime) == sha
        assert real.refusals == fixture.refusals


@pytest.mark.parametrize(
    "object_ids, uuid, value",
    [
        *[
            pytest.param(P2_LOOP_OBJECT_IDS[:1], SLIDE1, value, id=repr(value))
            for value in ["bogus", True, None, "loopBackAndForth", "", "Looping", 1, 0, False, []]
        ],
        # WA0125 never continues across a boundary; its vocabulary is checked all the same.
        pytest.param((P2_WA0125_OBJECT_ID,), SLIDE3, "loopBackAndForth", id="wa0125-no-boundary-carries"),
    ],
)
def test_an_unmeasured_loop_mode_value_refuses_the_whole_deck(object_ids, uuid, value):
    """L0-c (plan section 2.1): only "looping" was ever measured. The player also honours
    "loopBackAndForth" (as a plain loop), but no export has shown it, so it refuses like every
    other unmeasured vocabulary."""
    plan = derive_plan(_loop_tree(object_ids, value), SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert plan.reason == (
        f"movie on slide {uuid} has an unmeasured loopMode {value!r} (only 'looping' is qualified)"
    )


def test_an_object_valued_loop_mode_is_refused_as_a_possible_mask():
    """An object under `loopMode` never reaches the value check: the generic walk refuses it as
    unmeasured structure first."""
    plan = derive_plan(_loop_tree(P2_LOOP_OBJECT_IDS[:1], {"mode": "looping"}), SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "possible mask" in plan.reason
    assert "movie.loopMode" in plan.reason


def test_a_looping_movie_no_entry_names_leaves_the_runtime_alone():
    """WA0125 never continues, so no entry names it and its loop cannot reach the runtime."""
    plan = derive_plan(_loop_tree(P2_LOOP_OBJECT_IDS + (P2_WA0125_OBJECT_ID,)), SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == _plan().refusals
    assert plan.to_runtime() == _looping(EXPECTED_RUNTIME_PLAN)
    assert set(plan.loop_instances[2]) == {"untitled.mov", "vid-20250608-wa0125.mp4"}


def _loop_reason(from_index: int, to_index: int) -> str:
    return (
        f"'untitled.mov' loops on one side of player index {from_index} -> {to_index} only; "
        "a carried decoder keeps its source's loop setting"
    )


@pytest.mark.parametrize("gl_replay", [False, True])
def test_r4_a_loop_difference_on_the_bridge_retires_that_boundary(gl_replay, monkeypatch):
    """L0-b / R4: slide 3 loops, slide 4 does not. The 3->4 bridge is refused on its own and
    becomes a `retire`. 2->3 is a dissolve (fresh element each side), so it is not checked."""
    tree = _loop_tree((P2_OBJECT_IDS["slide3"],))
    plan = derive_plan(tree, SLIDES, resolver=_resolver, gl_replay=gl_replay)
    assert isinstance(plan, ContinuityPlan)
    bridge = plan.boundaries[2].movies[0]
    assert (bridge.action, bridge.refusal, bridge.code) == ("bridge", _loop_reason(2, 3), "R4")
    assert [(r["toPlayer"], r["code"]) for r in plan.refusals] == [(1, "overlap"), (3, "R4")]
    assert all(m.refusal is None for m in plan.boundaries[1].movies)
    runtime = _signed(monkeypatch, plan)
    assert runtime["boundaries"][-1] == {
        "atScene": 8, "action": "retire", "reason": "refused", "movieKey": "movie1",
        "src": {"objectId": P2_OBJECT_IDS["slide3"], "rect": P2_SLIDE3_MOVIE_RECT},
    }


def test_a_loop_difference_on_an_uncarried_instance_is_not_a_refusal():
    """The narrowed rule (plan section 2.4): only slide 1's SMALL instance loops, and it pairs with
    nothing, so the carried pair agrees and only the green square's overlap refuses 1->2."""
    tree = _loop_tree((P2_OBJECT_IDS["slide1_small"],))
    plan = derive_plan(tree, SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == _plan().refusals
    assert plan.to_runtime() == EXPECTED_RUNTIME_PLAN


def test_a_loop_difference_skips_gl_replay_and_says_why():
    """Flag on: a loop-refused boundary never reaches arming rules 1-5, and the record names the
    loop reason instead."""
    tree = _loop_tree((P2_OBJECT_IDS["slide2"],))
    plan = derive_plan(tree, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].movies[0]
    assert movie.refusal == _loop_reason(0, 1)
    assert movie.gl_replay is None
    assert movie.gl_replay_reason == _loop_reason(0, 1)
    assert movie.gl_replay_slot is None
    record = plan.refusals[0]
    assert (record["code"], record["glReplay"], record["glReplayReason"]) == ("R4", False, _loop_reason(0, 1))
    assert record["opacityExcluded"] == []


@pytest.mark.parametrize(
    "looping, refused",
    [
        ((P2_OBJECT_IDS["slide1"],), True),
        ((P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide1_small"]), True),
        ((P2_OBJECT_IDS["slide2"],), True),
        ((P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide2"]), False),
        ((P2_OBJECT_IDS["slide1_small"], P2_OBJECT_IDS["slide2"]), True),
    ],
    ids=["source-carried-only", "source-both", "destination-only", "carried-pair", "small-and-destination"],
)
def test_only_the_carried_pair_decides_the_loop_refusal(looping, refused):
    plan = derive_plan(_loop_tree(looping), SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].movies[0]
    assert (movie.code == "R4") is refused
    assert movie.refusal == (_loop_reason(0, 1) if refused else _plan().boundaries[0].movies[0].refusal)


def test_a_loop_difference_without_an_overlap_is_still_refused():
    """The loop rule does not ride on the overlap refusal: with the green square moved below
    the movie, 1->2 carries in P2 -- and a loop difference refuses it on its own."""
    tree = _loop_tree((P2_OBJECT_IDS["slide2"],))
    _rewrite_slide_json(tree, SLIDE2, _move_green_square_below_the_movie)
    plan = derive_plan(tree, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    assert plan.boundaries[0].movies[0].refusal == _loop_reason(0, 1)
    assert plan.boundaries[0].movies[0].gl_replay_reason == _loop_reason(0, 1)

    agreeing = _loop_tree()
    _rewrite_slide_json(agreeing, SLIDE2, _move_green_square_below_the_movie)
    carried = derive_plan(agreeing, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(carried, ContinuityPlan)
    assert carried.boundaries[0].movies[0].refusal is None
    assert carried.boundaries[0].movies[0].gl_replay_reason is None


def test_loop_instances_are_not_in_as_dict_and_default_to_empty():
    plan = derive_plan(_loop_tree(), SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert set(plan.as_dict()) == {
        "canvas", "sceneIndexByPlayer", "slideRects", "boundaries", "slideInstances", "refusals",
    }
    assert ContinuityPlan({"width": 1, "height": 1}, {0: 0}, {}, ()).loop_instances == {}


def test_emptied_loop_instances_do_not_change_the_runtime():
    """`loop_instances` is the probe's force-wrap ground truth only; the runtime reads `loop`
    from each entry."""
    plan = derive_plan(_loop_tree(), SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert replace(plan, loop_instances={}).to_runtime() == plan.to_runtime()


def _add_audio_only_movie(loop_mode, keep_video_layer: bool = False):
    """Slide 1 gains a synthetic audio-only movie node: `isAudioOnly` true and no video
    sub-layer (the player's `renderAudioOnlyEffect` path, which also sets `loop` from the same
    two literals). `_ABSENT_LOOP_MODE` leaves the key out; `keep_video_layer` is the positive
    control."""

    def transform(data):
        events = copy.deepcopy(data["events"])
        clone = copy.deepcopy(_find_movie_nodes(events)[0])
        clone["objectID"] = "SYNTHETIC-AUDIO-ONLY"
        clone["movie"] = {**clone["movie"], "asset": "Audio.m4a-0.0000-10.0000", "isAudioOnly": True}
        if loop_mode is not _ABSENT_LOOP_MODE:
            clone["movie"]["loopMode"] = loop_mode
        if not keep_video_layer:
            clone["baseLayer"]["layers"] = []
        events[0]["clonedMovies"] = [clone]
        assets = {
            **data["assets"],
            "Audio.m4a-0.0000-10.0000": {"type": "audio", "url": {"web": "assets/Audio.m4a-0.0000-10.0000.m4a"}},
        }
        return {**data, "events": events, "assets": assets}

    return transform


_ABSENT_LOOP_MODE = object()


@pytest.mark.parametrize("gl_replay", [False, True])
@pytest.mark.parametrize(
    "loop_mode",
    [_ABSENT_LOOP_MODE, "looping", "loopBackAndForth", "bogus", None, True, {"mode": "looping"}],
    ids=["absent", "looping", "loopBackAndForth", "bogus", "None", "True", "object"],
)
def test_an_audio_only_movie_is_refused_upstream_whatever_its_loop_mode(loop_mode, gl_replay):
    """Codex r1 F7: audio-only movies stay unmeasured (plan section 8 risk 3). They are refused
    before any loop rule runs -- `_movie_rect` needs exactly one video sub-layer -- so no loop
    value on one, qualified or not, can reach a runtime. The object value trips the vocabulary
    walk even earlier, which is also a whole-deck refusal."""
    tree = _mutate_slide(SLIDE1, _add_audio_only_movie(loop_mode))
    plan = derive_plan(tree, SLIDES, resolver=_resolver, gl_replay=gl_replay)
    assert isinstance(plan, Unsupported)
    if isinstance(loop_mode, dict):
        assert plan.reason.endswith("(possible mask): <movie node>.movie.loopMode")
    else:
        assert plan.reason == f"movie node on slide {SLIDE1} has 0 video sub-layers, expected 1"


def test_the_synthetic_audio_node_derives_when_its_video_sub_layer_is_kept():
    """Positive control for the test above: the same clone with its video sub-layer kept
    derives, so the refusal there is the missing sub-layer and nothing else in the synthetic."""
    tree = _mutate_slide(SLIDE1, _add_audio_only_movie("looping", keep_video_layer=True))
    plan = derive_plan(tree, SLIDES, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert plan.loop_instances == {0: {"audio.m4a": [_rect(*SLIDE1_BIG)]}}


# --- schema 2: per-boundary refusal codes and cut rules (generalisation plan section 2.3) ----


def _refusal_codes(plan: ContinuityPlan) -> list[tuple[int, str]]:
    return [(record["toPlayer"], record["code"]) for record in plan.refusals]


def _add_build(build_type: str, name: str, object_id: str | None):
    def apply(data):
        effect = {"name": name, "type": build_type, "beginTime": 0, "effects": []}
        if object_id is not None:
            effect["objectID"] = object_id
        data["events"][0]["effects"].append(effect)
        return data

    return apply


@pytest.mark.parametrize(
    "uuid, build_type, name, object_id, codes",
    [
        # Magic Move never pairs an object that builds in on the destination or out on the source
        # (F3); a build naming no object might be one, so it refuses too.
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", P2_OBJECT_IDS["slide4"], [(1, "overlap"), (3, "R2")], id="dst-builds-in"),
        pytest.param(SLIDE3, "buildOut", "apple:dissolve", P2_OBJECT_IDS["slide3"], [(1, "overlap"), (3, "R2")], id="src-builds-out"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", None, [(1, "overlap"), (3, "R2")], id="unattributed-build"),
        pytest.param(SLIDE4, "buildIn", "apple:movie-start", P2_OBJECT_IDS["slide4"], [(1, "overlap")], id="movie-start-build-does-not-refuse"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", "SOME-TEXT-BOX", [(1, "overlap")], id="build-on-another-object-does-not-refuse"),
        # Slide 2 -> 3 is a Dissolve, so a nameless build-out on slide 2 affects no carry; the
        # 1 -> 2 move only reads slide 2's build-ins.
        pytest.param(SLIDE2, "buildOut", "apple:dissolve", None, [(1, "overlap")], id="unattributed-build-on-a-slide-no-carry-touches"),
    ],
)
def test_r2_a_carried_instance_that_builds_refuses_the_boundary(uuid, build_type, name, object_id, codes):
    plan = _plan(_mutate_slide(uuid, _add_build(build_type, name, object_id)))
    assert isinstance(plan, ContinuityPlan)
    assert _refusal_codes(plan) == codes


def test_r3_a_transition_off_the_last_event_refuses_the_deck():
    def move_transition_to_the_first_event(data):
        transition = data["events"][-1]["effects"].pop(0)
        assert transition["type"] == "transition"
        data["events"][0]["effects"].append(transition)
        return data

    plan = _plan(_mutate_slide(SLIDE1, move_transition_to_the_first_event))
    assert isinstance(plan, Unsupported)
    assert plan.reason.startswith(f"R3: slide {SLIDE1}'s transition is not on its last event")


def _set_movie_field(object_id: str, key: str, value):
    def apply(node):
        if node.get("objectID") == object_id:
            node["movie"][key] = value

    return lambda data: _map_movie_nodes(data, apply)


def _set_asset_url(url: str):
    def apply(data):
        for entry in data["assets"].values():
            if entry.get("url", {}).get("web", "").startswith("assets/Untitled.mov"):
                entry["url"] = {"web": url, "native": url}
        return data

    return apply


@pytest.mark.parametrize(
    "transform, kind",
    [
        (_set_movie_field(P2_OBJECT_IDS["slide4"], "isStreaming", True), "web"),
        (_set_asset_url("assets/Untitled.mov-0.0000-46.0333.png"), "image"),
        (_set_asset_url("https://example.invalid/Untitled.mov-0.0000-46.0333.mov"), "web"),
    ],
    ids=["streaming", "image", "remote-url"],
)
def test_r7_a_movie_the_player_draws_without_a_video_refuses_the_boundary(transform, kind):
    plan = _plan(_mutate_slide(SLIDE4, transform))
    assert isinstance(plan, ContinuityPlan)
    assert _refusal_codes(plan) == [(1, "overlap"), (3, "R7")]
    assert f"is a {kind} movie" in plan.refusals[1]["reason"]


@pytest.mark.parametrize(
    "transform",
    [
        _set_movie_field(P2_OBJECT_IDS["slide4"], "endTime", 40.0),
        _set_movie_field(P2_OBJECT_IDS["slide4"], "startTime", 1.0),
        _set_asset_url("assets/Untitled.mov-0.0000-40.0000.mov"),
    ],
    ids=["end-time", "start-time", "url-trim-suffix"],
)
def test_r8_a_trim_mismatch_refuses_the_boundary(transform):
    """`_TRIM_SUFFIX_RE` folds differently trimmed clips of one file into one asset key, so the
    trim itself must match for the pair to be one continuous movie."""
    plan = _plan(_mutate_slide(SLIDE4, transform))
    assert isinstance(plan, ContinuityPlan)
    assert plan.boundaries[2].movies[0].asset == "untitled.mov"
    assert _refusal_codes(plan) == [(1, "overlap"), (3, "R8")]


# --- R9: a carried instance must be fully opaque (S2 review r2 #2) ---------------------------
#
# Every carry path (bridge reparent, settled hold, pin keep-at-slot, the glReplay hand-off) sets
# the decoder's `opacity` to 1 outside its authored layers, and the runtime plan carries no
# opacity at all. R1b only compares opacities when there is a pairing CHOICE, so a single
# translucent pair, or repeated instances that all agree on a translucent opacity, used to carry.
# The export exposes opacity on the movie node's own layers (movie layer, video sub-layer, the
# poster's `singleTextureOpacity`) and on the slide's draw tree (the draw slot wrapper and the
# object layer it holds); all of them must read exactly 1.

OPACITY_SOURCES = ["movie layer", "video layer", "draw slot object", "draw slot wrapper"]


def _set_opacity(object_id: str, value, where: str = "movie layer"):
    def apply(data):
        data = copy.deepcopy(data)
        for node in _find_movie_nodes(data["events"]):
            if node.get("objectID") != object_id:
                continue
            base = node["baseLayer"]
            if where == "movie layer":
                base["initialState"]["opacity"] = value
            elif where == "video layer":
                next(layer for layer in base["layers"] if layer.get("isVideoLayer"))["initialState"]["opacity"] = value
        if where.startswith("draw slot"):
            drawn = _events_drawing(data, object_id)
            assert drawn, f"{object_id} has no draw slot to mutate"
            for index in drawn:
                for slot in _draw_slots(data, index):
                    if len(slot["layers"]) == 1 and slot["layers"][0].get("objectID") == object_id:
                        target = slot["layers"][0] if where == "draw slot object" else slot
                        target.setdefault("initialState", {})["opacity"] = value
        return data

    return apply


def _with_opacities(*changes) -> Path:
    """A fixture copy with each (slide uuid, P2_OBJECT_IDS key, value, where) applied in turn."""
    root = _copy_fixture_tree()
    for uuid, key, value, where in changes:
        _rewrite_slide_json(root, uuid, _set_opacity(P2_OBJECT_IDS[key], value, where))
    return root


@pytest.mark.parametrize("where", OPACITY_SOURCES)
def test_r9_a_single_translucent_bridge_refuses_the_boundary(where):
    """Slide 3 -> 4 is one instance on each side, so R1b never looks at it."""
    root = _with_opacities((SLIDE3, "slide3", 0.5, where), (SLIDE4, "slide4", 0.5, where))
    plan = _plan(root)
    assert isinstance(plan, ContinuityPlan)
    [bridge] = plan.boundaries[2].movies
    assert (bridge.action, bridge.code, bridge.src_object_id, bridge.dst_object_id) == (
        "bridge", "R9", P2_OBJECT_IDS["slide3"], P2_OBJECT_IDS["slide4"],
    )
    assert "is not fully opaque" in bridge.refusal
    assert _refusal_codes(plan) == [(1, "overlap"), (3, "R9")]


@pytest.mark.parametrize("where", OPACITY_SOURCES)
@pytest.mark.parametrize("uuid, key, side", [(SLIDE3, "slide3", "source"), (SLIDE4, "slide4", "destination")])
def test_r9_an_opacity_change_across_the_move_refuses_the_boundary(uuid, key, side, where):
    plan = _plan(_with_opacities((uuid, key, 0.5, where)))
    assert isinstance(plan, ContinuityPlan)
    [bridge] = plan.boundaries[2].movies
    assert (bridge.action, bridge.code) == ("bridge", "R9")
    assert bridge.refusal == (
        f"'untitled.mov' is not fully opaque on the {side} slide of player index 2 -> 3; "
        "a carried decoder is drawn at opacity 1"
    )


@pytest.mark.parametrize("gl_replay", [False, True])
def test_r9_repeated_instances_that_agree_on_a_translucent_opacity_refuse_the_pin_and_gl_replay(gl_replay):
    """All three slide 1 -> 2 candidates at 0.5: R1b sees no difference and pairs by distance.
    The pin is refused before its overlap is considered, so glReplay (which hands off to the
    same opacity-1 hold) is not derived either."""
    root = _with_opacities(
        (SLIDE1, "slide1", 0.5, "movie layer"),
        (SLIDE1, "slide1_small", 0.5, "movie layer"),
        (SLIDE2, "slide2", 0.5, "movie layer"),
    )
    plan = derive_plan(root, SLIDES, resolver=_resolver, gl_replay=gl_replay)
    assert isinstance(plan, ContinuityPlan)
    [pin] = plan.boundaries[0].movies
    assert (pin.action, pin.code, pin.src_object_id, pin.dst_object_id) == (
        "pin", "R9", P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide2"],
    )
    assert pin.gl_replay is None
    assert pin.gl_replay_reason == (pin.refusal if gl_replay else None)
    assert _refusal_codes(plan) == [(1, "R9")]


@pytest.mark.parametrize("value", [0.999, 0, True, "1", None], ids=["near-one", "zero", "bool", "string", "null"])
def test_r9_only_an_exact_numeric_one_is_opaque(value):
    plan = _plan(_with_opacities((SLIDE4, "slide4", value, "movie layer")))
    assert isinstance(plan, ContinuityPlan)
    assert _refusal_codes(plan) == [(1, "overlap"), (3, "R9")]


@pytest.mark.parametrize("layer", ["movie layer", "video layer"])
def test_r9_a_movie_layer_that_exports_no_opacity_is_not_assumed_opaque(layer):
    def drop(node):
        if node.get("objectID") == P2_OBJECT_IDS["slide4"]:
            base = node["baseLayer"]
            target = base if layer == "movie layer" else next(l for l in base["layers"] if l.get("isVideoLayer"))
            del target["initialState"]["opacity"]

    plan = _plan(_mutate_slide(SLIDE4, lambda data: _map_movie_nodes(data, drop)))
    assert isinstance(plan, ContinuityPlan)
    assert _refusal_codes(plan) == [(1, "overlap"), (3, "R9")]


@pytest.mark.parametrize("gl_replay", [False, True])
def test_r9_an_explicit_unit_opacity_everywhere_still_carries(gl_replay):
    """Guard: writing opacity 1.0 into every source the rule reads -- including the draw-tree
    keys the trimmed fixture omits -- changes nothing, glReplay included."""
    changes = [
        (uuid, key, 1.0, where)
        for uuid, key in (
            (SLIDE1, "slide1"), (SLIDE1, "slide1_small"), (SLIDE2, "slide2"), (SLIDE3, "slide3"), (SLIDE4, "slide4"),
        )
        for where in OPACITY_SOURCES
    ]
    plan = derive_plan(_with_opacities(*changes), SLIDES, resolver=_resolver, gl_replay=gl_replay)
    baseline = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=gl_replay)
    assert isinstance(plan, ContinuityPlan)
    assert plan.as_dict() == baseline.as_dict()
    assert [m.action for b in plan.boundaries for m in b.movies] == ["pin", "restart", "bridge", "restart"]
    assert (plan.boundaries[0].movies[0].gl_replay is not None) is gl_replay


def _parsed_slide(player_index: int, uuid: str, root: Path = FIXTURE_ROOT):
    from obed_edom.live_continuity import _Slide, _slide_movie_instances

    data = json.loads((root / "assets" / uuid / f"{uuid}.json").read_text())
    return _Slide(player_index, uuid, data["events"], _slide_movie_instances(data["events"], data["assets"], uuid))


def test_a_later_gl_replay_eligible_boundary_retires_instead():
    """OQ-4: G2 arms exactly one boundary; a later eligible one keeps its refusal (retire)."""
    from obed_edom.live_continuity import _boundary_transition, _magic_move_movies

    source, destination = _parsed_slide(0, SLIDE1), _parsed_slide(1, SLIDE2)
    transition = _boundary_transition(source.events, SLIDE1)
    args = (source, destination, set(), "1 -> 2", transition, transition["name"], True)
    [first] = _magic_move_movies(*args, False)
    [later] = _magic_move_movies(*args, True)
    assert first.gl_replay is not None
    assert (later.gl_replay, later.code) == (None, "overlap")
    assert later.gl_replay_reason == "a glReplay boundary is already planned (one per plan)"


def test_to_runtime_refuses_two_gl_replay_entries():
    plan = derive_plan(FIXTURE_ROOT, SLIDES, resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    armed = plan.boundaries[0].movies[0]
    bridge = plan.boundaries[2].movies[0]
    second = replace(
        armed, src_rect=bridge.src_rect, dst_rect=bridge.dst_rect,
        src_object_id=P2_OBJECT_IDS["slide3"], dst_object_id=P2_OBJECT_IDS["slide4"],
    )
    doubled = replace(
        plan, boundaries=(*plan.boundaries[:2], replace(plan.boundaries[2], movies=(second,)), plan.boundaries[3])
    )
    assert doubled.to_runtime() == Unsupported("more than one glReplay boundary (G2 arms exactly one)")


def test_a_cut_restarts_every_video_instance_whose_asset_continues():
    """Slide 1's two instances cross a (hypothetical) dissolve onto slide 2: each gets its own
    `restart`, naming slide 2's only instance as its informational destination."""
    from obed_edom.live_continuity import _cut_movies

    movies = _cut_movies(_parsed_slide(0, SLIDE1), _parsed_slide(1, SLIDE2), set(), "0 -> 1")
    assert [(m.action, m.src_object_id, m.dst_object_id) for m in movies] == [
        ("restart", P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide2"]),
        ("restart", P2_OBJECT_IDS["slide1_small"], P2_OBJECT_IDS["slide2"]),
    ]


def test_a_cut_ends_a_carried_instance_whose_asset_does_not_continue():
    """WA0125, if it were carried onto slide 3, would have nothing on slide 4 to become: `retire`
    (reason `ends`); an uncarried instance with no successor gets no entry at all."""
    from obed_edom.live_continuity import _cut_movies

    source, destination = _parsed_slide(2, SLIDE3), _parsed_slide(3, SLIDE4)
    held = _cut_movies(source, destination, {P2_OBJECT_IDS["slide3_wa0125"]}, "2 -> 3")
    assert [(m.action, m.src_object_id, m.refusal) for m in held] == [
        ("restart", P2_OBJECT_IDS["slide3"], None),
        ("retire", P2_OBJECT_IDS["slide3_wa0125"], None),
    ]
    assert [m.action for m in _cut_movies(source, destination, set(), "2 -> 3")] == ["restart"]


def test_a_magic_move_ends_a_carried_instance_that_pairs_with_nothing():
    """At a Magic Move an unpaired outgoing instance gets `retire ends` only when it is carried."""
    from obed_edom.live_continuity import _boundary_transition, _magic_move_movies

    source, destination = _parsed_slide(2, SLIDE3), _parsed_slide(3, SLIDE4)
    transition = _boundary_transition(source.events, SLIDE3)
    args = (source, destination)
    tail = ("3 -> 4", transition, transition["name"], False, False)
    carried = _magic_move_movies(*args, {P2_OBJECT_IDS["slide3_wa0125"]}, *tail)
    assert [(m.action, m.asset) for m in carried] == [("bridge", "untitled.mov"), ("retire", "vid-20250608-wa0125.mp4")]
    assert [m.action for m in _magic_move_movies(*args, set(), *tail)] == ["bridge"]


def test_movie_table_names_only_assets_with_an_entry_and_footprints_their_first_instance():
    """WA0125 has no entry, so it is not in `movies` and the runtime cannot pool it (the stray
    62e1ab7 fixed); movie1's footprint is P2's instrument constant."""
    runtime = _plan().to_runtime()
    assert isinstance(runtime, dict)
    assert runtime["movies"] == {"movie1": {"assetKeys": ["untitled.mov"], "footprint": P2_MOVIE1_FOOTPRINT}}


def test_a_mid_deck_none_transition_is_a_cut_like_a_dissolve():
    """Keynote exports "no transition" as the name `none` (S0: every last slide). Mid-deck it is a
    cut: the continuing movie restarts, and the Magic Move after it still carries."""
    plan = _plan(_mutate_slide(SLIDE2, lambda data: _map_transitions(data, lambda _name: "none")))
    assert isinstance(plan, ContinuityPlan)
    assert [m.action for m in plan.boundaries[1].movies] == ["restart"]
    assert plan.to_runtime() == EXPECTED_RUNTIME_PLAN


def test_an_unknown_transition_name_still_refuses_the_deck():
    plan = _plan(_mutate_slide(SLIDE2, lambda data: _map_transitions(data, lambda _name: "apple:cube")))
    assert plan == Unsupported("unsupported transition 'apple:cube' at player index 1 -> 2")


def test_r2_an_unattributed_build_says_it_cannot_be_ruled_out():
    """Only the carried pair's own slides count, and the reason says plainly why it refuses, so a
    real-deck dry run surfaces it."""
    plan = _plan(_mutate_slide(SLIDE4, _add_build("buildIn", "apple:dissolve", None)))
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals[1]["reason"] == (
        f"a build-in ('apple:dissolve') on slide {SLIDE4} at player index 2 -> 3 names no object, and the "
        "export gives no other way to tell whether it builds 'untitled.mov', so the carry is refused "
        "rather than guessed"
    )


# --- R2 before pairing, nested builds, and cuts onto a web destination (S2 Codex r1) ---------


def _clone_onto_slide2_top_right(data):
    """Slide 2 gains a second untitled.mov instance, objectID CLONE, the size of slide 1's small
    instance but centred far above it, drawn on top of everything so no overlap refuses it."""
    data = _clone_second_instance_onto_slide2(data)
    clone = data["events"][-1]["effects"][0]["effects"][-1]
    clone["objectID"] = "CLONE"
    _, (small_x, _) = _slide1_centres()
    clone["baseLayer"]["initialState"]["position"] = {"pointX": small_x, "pointY": 100.0}
    w, h = SLIDE1_SMALL[2], SLIDE1_SMALL[3]
    _draw_slots(data, 0).append(_authored_slot(small_x - w / 2, 100.0 - h / 2, w, h, object_id="CLONE"))
    return data


def test_r2_the_repeated_instance_geometry_pairs_the_sibling_onto_the_far_destination():
    """Positive control for the test below, with no build anywhere: sources A (slide 1's big
    instance) and B (its small one), destinations C (slide 2's instance, A's rect) and CLONE (far
    above B). The minimum-total assignment is A->C, B->CLONE; B alone would pair with C, which is
    nearer to it than CLONE by well over the 16 px margin."""
    from obed_edom.live_continuity import _pair_instances

    plan = _plan(_mutate_slide(SLIDE2, _clone_onto_slide2_top_right))
    assert isinstance(plan, ContinuityPlan)
    assert [(m.action, m.src_object_id, m.dst_object_id, m.code) for m in plan.boundaries[0].movies] == [
        ("pin", P2_OBJECT_IDS["slide1"], P2_OBJECT_IDS["slide2"], "overlap"),
        ("bridge", P2_OBJECT_IDS["slide1_small"], "CLONE", None),
    ]
    source, destination = _parsed_slide(0, SLIDE1), _parsed_slide(
        1, SLIDE2, _mutate_slide(SLIDE2, _clone_onto_slide2_top_right)
    )
    [small] = [i for i in source.instances["untitled.mov"] if i.object_id == P2_OBJECT_IDS["slide1_small"]]
    pairs, refusal = _pair_instances([small], destination.instances["untitled.mov"], set())
    assert refusal is None
    assert [(src.object_id, dst.object_id) for src, dst in pairs] == [
        (P2_OBJECT_IDS["slide1_small"], P2_OBJECT_IDS["slide2"])
    ]


def test_r2_a_building_instance_of_a_repeated_asset_refuses_its_whole_pairing():
    """The review's shape: A builds out, so Keynote (validate._mm_matches' model, measured on
    images, not movies) would drop A and move B onto C. Distance-pairing first and refusing A->C
    afterwards would carry B onto CLONE instead, a destination Keynote never moves it to. Which
    pairing Keynote makes for the rest is unmeasured for movies, so every instance of the asset
    is refused at that boundary (R2), as an ambiguous pairing is (R1)."""
    root = _mutate_slide(SLIDE2, _clone_onto_slide2_top_right)
    _rewrite_slide_json(root, SLIDE1, _add_build("buildOut", "apple:dissolve", P2_OBJECT_IDS["slide1"]))
    plan = _plan(root)
    assert isinstance(plan, ContinuityPlan)
    movies = plan.boundaries[0].movies
    assert [(m.action, m.code, m.src_object_id, m.dst_object_id) for m in movies] == [
        ("retire", "R2", P2_OBJECT_IDS["slide1"], None),
        ("retire", "R2", P2_OBJECT_IDS["slide1_small"], None),
    ]
    assert movies[0].refusal == (
        "'untitled.mov' pairing at player index 0 -> 1: an instance builds in or out, which Magic Move "
        "leaves unpaired, and how Keynote then pairs the rest of a movie is unmeasured"
    )
    assert "CLONE" not in json.dumps(plan.as_dict()["boundaries"][0])


def test_r2_a_destination_build_in_on_a_repeated_asset_refuses_its_whole_pairing():
    root = _mutate_slide(SLIDE2, _clone_onto_slide2_top_right)
    _rewrite_slide_json(root, SLIDE2, _add_build("buildIn", "apple:dissolve", P2_OBJECT_IDS["slide2"]))
    plan = _plan(root)
    assert isinstance(plan, ContinuityPlan)
    assert [(m.action, m.code) for m in plan.boundaries[0].movies] == [("retire", "R2"), ("retire", "R2")]


def _nest_build(build_type: str, name: str, object_id: str | None, *, leader: str):
    """A build "with previous" nests in its leader's `effects`. `leader="movie-start"` nests it
    under event 0's first effect, the slide movie's own `apple:movie-start`; `leader="text"`
    under a new top-level build of another object."""

    def apply(data):
        effect = {"name": name, "type": build_type, "beginTime": 0, "effects": []}
        if object_id is not None:
            effect["objectID"] = object_id
        first = data["events"][0]["effects"]
        if leader == "movie-start":
            assert first[0]["name"] == "apple:movie-start"
            first[0]["effects"].append(effect)
        else:
            first.append(
                {"name": "apple:dissolve", "type": build_type, "beginTime": 0, "objectID": "SOME-TEXT-BOX",
                 "effects": [effect]}
            )
        return data

    return apply


@pytest.mark.parametrize(
    "uuid, build_type, name, object_id, leader, codes",
    [
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", P2_OBJECT_IDS["slide4"], "text", [(1, "overlap"), (3, "R2")], id="dst-nested-under-another-build"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", P2_OBJECT_IDS["slide4"], "movie-start", [(1, "overlap"), (3, "R2")], id="dst-nested-under-the-movie-start"),
        pytest.param(SLIDE3, "buildOut", "apple:dissolve", P2_OBJECT_IDS["slide3"], "text", [(1, "overlap"), (3, "R2")], id="src-nested-under-another-build"),
        pytest.param(SLIDE3, "buildOut", "apple:dissolve", P2_OBJECT_IDS["slide3"], "movie-start", [(1, "overlap"), (3, "R2")], id="src-nested-under-the-movie-start"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", None, "text", [(1, "overlap"), (3, "R2")], id="unattributed-nested"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", None, "movie-start", [(1, "overlap"), (3, "R2")], id="unattributed-nested-under-the-movie-start"),
        # Only the movie-start build itself and its own renderMovie child are exempt (F3).
        pytest.param(SLIDE4, "buildIn", "renderMovie", P2_OBJECT_IDS["slide4"], "text", [(1, "overlap"), (3, "R2")], id="render-movie-outside-a-movie-start"),
        pytest.param(SLIDE4, "buildIn", "apple:movie-start", P2_OBJECT_IDS["slide4"], "text", [(1, "overlap")], id="nested-movie-start-does-not-refuse"),
        pytest.param(SLIDE4, "buildIn", "renderMovie", P2_OBJECT_IDS["slide4"], "movie-start", [(1, "overlap")], id="render-movie-of-a-movie-start-does-not-refuse"),
        pytest.param(SLIDE4, "buildIn", "apple:dissolve", "OTHER-OBJECT", "movie-start", [(1, "overlap")], id="nested-build-on-another-object-does-not-refuse"),
    ],
)
def test_r2_a_nested_build_refuses_the_boundary(uuid, build_type, name, object_id, leader, codes):
    plan = _plan(_mutate_slide(uuid, _nest_build(build_type, name, object_id, leader=leader)))
    assert isinstance(plan, ContinuityPlan)
    assert _refusal_codes(plan) == codes


def _web_slide3_after_a_clean_1_to_2_pin(*, slide3_kind_field=("isStreaming", True)) -> Path:
    """Slide 2's green square moves behind the movie, so the 1 -> 2 pin carries unrefused and
    slide 2's instance is held into the 2 -> 3 Dissolve; slide 3's untitled.mov is then made a
    web video, which the player draws as an <iframe>, never a <video>."""
    root = _mutate_slide(SLIDE2, _move_green_square_below_the_movie)
    _rewrite_slide_json(root, SLIDE3, _set_movie_field(P2_OBJECT_IDS["slide3"], *slide3_kind_field))
    return root


def test_r7_a_cut_from_a_carried_video_onto_a_web_destination_refuses_instead_of_restarting():
    """A restart's carried decoder is retired only when a fresh <video> of its asset sets `src`
    at or after `atScene`. A web destination never creates one, so `restart` would leave the held
    decoder alive; the boundary is refused (R7) and the decoder retired from `atScene - 1`."""
    plan = _plan(_web_slide3_after_a_clean_1_to_2_pin())
    assert isinstance(plan, ContinuityPlan)
    assert [(m.action, m.src_object_id) for m in plan.boundaries[0].movies] == [("pin", P2_OBJECT_IDS["slide1"])]
    assert plan.boundaries[0].movies[0].refusal is None
    [cut] = plan.boundaries[1].movies
    assert (cut.action, cut.code, cut.src_object_id, cut.dst_object_id) == ("retire", "R7", P2_OBJECT_IDS["slide2"], None)
    assert cut.refusal == "'untitled.mov' at player index 1 -> 2 is a web movie, which the player draws without a <video>"
    assert (1, "R7") in [(r["fromPlayer"], r["code"]) for r in plan.refusals]


def test_r7_a_cut_onto_a_web_destination_retires_in_the_runtime_plan(monkeypatch):
    from obed_edom import live_continuity

    plan = _plan(_web_slide3_after_a_clean_1_to_2_pin())
    assert isinstance(plan, ContinuityPlan)
    monkeypatch.setattr(live_continuity, "plan_signature", lambda _runtime: next(iter(live_continuity.QUALIFIED_PLAN_SHA256)))
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    at_scene_6 = [b for b in runtime["boundaries"] if b["atScene"] == 6]
    assert [(b["action"], b.get("reason"), b["src"]["objectId"]) for b in at_scene_6] == [
        ("retire", "refused", P2_OBJECT_IDS["slide2"])
    ]
    assert not any(b["action"] == "restart" for b in runtime["boundaries"] if b["atScene"] == 6)


def test_a_cut_onto_an_image_destination_refuses_too():
    root = _mutate_slide(SLIDE2, _move_green_square_below_the_movie)
    _rewrite_slide_json(root, SLIDE3, _set_asset_url("assets/Untitled.mov-0.0000-46.0333.png"))
    plan = _plan(root)
    assert isinstance(plan, ContinuityPlan)
    [cut] = plan.boundaries[1].movies
    assert (cut.action, cut.code) == ("retire", "R7")
    assert "is a image movie" in cut.refusal


def test_a_cut_restarts_when_any_destination_instance_is_a_video():
    """A fresh <video> of the asset still sets `src` on the far side, so the restart retires the
    carried decoder as before; only an all-non-video far side is refused."""
    from obed_edom.live_continuity import _cut_movies

    source = _parsed_slide(0, SLIDE1)
    destination = _parsed_slide(1, SLIDE2, _mutate_slide(SLIDE2, _clone_onto_slide2_top_right))
    first, *rest = destination.instances["untitled.mov"]
    mixed = replace(destination, instances={"untitled.mov": [replace(first, kind="web"), *rest]})
    movies = _cut_movies(source, mixed, {P2_OBJECT_IDS["slide1"]}, "0 -> 1")
    assert [m.action for m in movies] == ["restart", "restart"]
