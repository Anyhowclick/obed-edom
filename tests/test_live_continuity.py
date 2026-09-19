from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from obed_edom.live_continuity import ContinuityPlan, MovieContinuity, Rect, Unsupported, codec_report, derive_plan

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
REAL_EXPORT_ROOT = Path(
    "/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/"
    "keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-unmodified"
)

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


def test_boundary_1_to_2_pins_the_static_movie():
    plan = _plan()
    boundary = _boundary(plan, 0)
    assert boundary["toPlayerIndex"] == 1
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "pin"
    assert untitled["srcRect"] == _rect(109.35, 795.04, 951.54, 267.62)
    assert untitled["dstRect"] == _rect(109.35, 795.04, 951.54, 267.62)


def test_boundary_2_to_3_restarts_across_the_dissolve():
    plan = _plan()
    boundary = _boundary(plan, 1)
    assert boundary["toPlayerIndex"] == 2
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    assert movies["untitled.mov"]["action"] == "restart"


def test_boundary_3_to_4_bridges_the_moving_scaling_movie():
    plan = _plan()
    boundary = _boundary(plan, 2)
    assert boundary["toPlayerIndex"] == 3
    assert boundary["durationSeconds"] == 1.5
    movies = {m["asset"]: m for m in boundary["movies"]}
    # WA0125 does not appear on slide 4: it must not be treated as continuing.
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "bridge"
    assert untitled["srcRect"] == _rect(197.98, 797.10, 951.54, 267.62)
    assert untitled["dstRect"] == _rect(326.75, 708.52, 1266.49, 356.20)


def test_boundary_4_to_end_restarts_with_no_destination():
    plan = _plan()
    boundary = _boundary(plan, 3)
    assert boundary["toPlayerIndex"] is None
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "restart"
    assert untitled["dstRect"] is None


def test_slide3_authored_y_differs_from_p2s_measured_constant_within_tolerance():
    """Known discrepancy (plan section 2): a previous analysis derived y=797 for slide 3's
    movie while P2's screen-measured MOVIE constant used 795 (authored notes: 794.6). The
    export data says y=797.10 (see test_boundary_3_to_4_bridges_the_moving_scaling_movie);
    P2's 795 is off by ~2.1px, comfortably inside the probe's stated 10px per-axis tolerance,
    consistent with it being a screen-measured rather than authored value. This test pins the
    DATA value; it must not be relaxed to force-fit 795.
    """
    plan = _plan()
    boundary = _boundary(plan, 2)
    src = next(m for m in boundary["movies"] if m["asset"] == "untitled.mov")["srcRect"]
    assert src["y"] == pytest.approx(797.10, abs=0.05)
    p2_measured_y = 795
    assert abs(src["y"] - p2_measured_y) < 10


def test_ambiguous_same_asset_instance_resolves_by_unique_geometry_match():
    """Slide 1 (player index 0) authors TWO Untitled.mov instances (see
    test_boundary_1_to_2_pins_the_static_movie's srcRect and the second, non-continuing
    instance at ~(1076, 876), matching the plan's noted 'movie2' drift). Only one of them
    has an identical-geometry counterpart on slide 2, so ownership is not actually ambiguous:
    the narrow rule is 'refuse only when more than one instance has a geometry-equal match on
    the far side', not 'refuse whenever more than one instance of an asset exists'. This is
    exactly the fixture P2 qualified, so it must still resolve to plan (not Unsupported).
    """
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    boundary = _boundary(plan, 0)
    assert len(boundary["movies"]) == 1


def test_ambiguous_ownership_is_refused_when_the_stray_instance_also_matches():
    """Mutate slide 2 so its lone Untitled.mov instance geometry equals slide 1's SECOND
    (non-continuing) instance as well as its first: now two geometry-equal pairs exist and
    ownership is genuinely ambiguous, which must fail closed."""
    tmp = _mutate_slide(SLIDE2, _clone_second_instance_onto_slide2)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "ambiguous" in plan.reason


def test_refuses_unreadable_header():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / "header.json").write_text("{not json")
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "header" in plan.reason


def test_refuses_slide_with_no_events():
    tmp = _copy_fixture_tree()
    _rewrite_slide_json(tmp, SLIDE1, lambda data: {**data, "events": []})
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "no events" in plan.reason


def test_refuses_unreadable_slide_json():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / SLIDE1 / f"{SLIDE1}.json").write_text("not json at all")
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unreadable slide export" in plan.reason


def test_refuses_unknown_transition_kind():
    tmp = _copy_fixture_tree()

    def rename(data):
        return _map_transitions(data, lambda name: "apple:cube")

    _rewrite_slide_json(tmp, SLIDE1, rename)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unsupported transition" in plan.reason


def test_refuses_rotated_movie_layer():
    tmp = _copy_fixture_tree()

    def rotate(data):
        return _map_movie_nodes(data, lambda node: _set_rotation(node, 5))

    _rewrite_slide_json(tmp, SLIDE1, rotate)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "rotated" in plan.reason or "transformed" in plan.reason


def test_refuses_non_identity_affine_transform():
    tmp = _copy_fixture_tree()

    def skew(data):
        return _map_movie_nodes(data, lambda node: _set_affine(node, [1, 0.2, 0, 1, 0, 0]))

    _rewrite_slide_json(tmp, SLIDE1, skew)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)


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
    assert "not a direct child" in plan.reason


def test_refuses_two_geometry_changing_movies_on_one_boundary():
    tmp = _copy_fixture_tree()

    # Slide 3 already carries a WA0125 instance; add a matching one on slide 4 so it also
    # "continues" (with different geometry) across the 3->4 magic move alongside Untitled.mov.
    def add_wa0125_to_slide4(data):
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

    _rewrite_slide_json(tmp, SLIDE4, add_wa0125_to_slide4)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "more than one movie" in plan.reason


def test_skipped_slide_does_not_shift_scene_indices():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 4, "originalOrdinal": 5, "exportedUuid": "does-not-exist", "skipped": True})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert plan.scene_index_by_player == {0: 0, 1: 2, 2: 6, 3: 8}


def test_skipped_slide_missing_uuid_is_ignored():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 9, "skipped": True})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)


def test_non_skipped_slide_missing_uuid_is_refused():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 9, "skipped": False})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, Unsupported)


def test_path_traversal_is_impossible():
    slides = copy.deepcopy(SLIDES)
    slides[0]["exportedUuid"] = "../../../../etc"
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unreadable slide export" in plan.reason


def test_plan_round_trips_through_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    restored = json.loads(plan.to_json())
    assert restored == plan.as_dict()
    assert restored["canvas"] == {"width": 1920, "height": 1080}
    assert restored["sceneIndexByPlayer"]["2"] == 6


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

# `derive_plan` on the fixture must produce exactly this runtime plan (plan section 1's "After").
EXPECTED_RUNTIME_PLAN = {
    "movies": {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 109, "y": 795, "w": 952, "h": 268}}},
    "boundaries": [
        {"atScene": 2, "action": "retire", "movieKey": "movie1"},
        {"atScene": 6, "action": "restart"},
        {
            "atScene": 8, "action": "bridge", "movieKey": "movie1",
            "srcRect": {"x": 198, "y": 797, "w": 952, "h": 268},
            "durationSeconds": 1.5,
            "rect": {"x": 327, "y": 709, "w": 1266, "h": 356},
        },
    ],
}
EXPECTED_PLAN_SHA256 = "bafe26cad55cf3a390154bce2c0fdcc771b9b1821293b6aec76119d25180e81e"

# The green square is slide 2's draw slot 6; the movie is slot 5.
SLIDE2_GREEN_SLOT = 6
SLIDE2_MOVIE_SLOT = 5


def _rect_close(a: dict, b: dict, tol: float = 3.0) -> bool:
    return all(abs(a[k] - b[k]) <= tol for k in ("x", "y", "w", "h"))


def test_to_runtime_matches_p2_injected_plan():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)

    # The fixture's WA0125 instance is only single (unambiguous) on player index 2,
    # not the first slide, so it does not enter the movie table -- it never
    # continues across a boundary, so the runtime does not need to classify it.
    assert "movie1" in runtime["movies"]
    movie1 = runtime["movies"]["movie1"]
    assert movie1["assetKeys"] == ["untitled.mov"]
    assert _rect_close(movie1["footprint"], P2_MOVIE1_FOOTPRINT)

    boundaries = {b["atScene"]: b for b in runtime["boundaries"]}
    assert set(boundaries) == {P2_SLIDE2_MIN_HASH, P2_SLIDE3_MIN_HASH, P2_SLIDE4_MIN_HASH}
    assert boundaries[P2_SLIDE2_MIN_HASH] == {
        "atScene": P2_SLIDE2_MIN_HASH, "action": "retire", "movieKey": "movie1",
    }
    assert boundaries[P2_SLIDE3_MIN_HASH]["action"] == "restart"
    bridge = boundaries[P2_SLIDE4_MIN_HASH]
    assert bridge["action"] == "bridge"
    assert bridge["movieKey"] == "movie1"
    assert bridge["srcRect"] == P2_SLIDE3_MOVIE_RECT
    assert bridge["durationSeconds"] == 1.5
    assert _rect_close(bridge["rect"], P2_SLIDE4_MOVIE_RECT)


def test_to_runtime_refuses_when_no_boundaries():
    plan = ContinuityPlan(canvas={"width": 1, "height": 1}, scene_index_by_player={0: 0}, slide_rects={}, boundaries=())
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)


def test_to_runtime_refuses_bridge_without_source_rect():
    plan = _plan()
    bridge = replace(
        plan.boundaries[2],
        movies=tuple(replace(movie, src_rect=None) for movie in plan.boundaries[2].movies),
    )
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "no source rect" in result.reason


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


@pytest.mark.parametrize("action", ["bridge", "restart", "pin"])
def test_to_runtime_refuses_actionable_boundaries_after_bridge(action):
    plan = _plan()
    bridge = plan.boundaries[2]
    following = replace(
        bridge,
        from_player_index=3,
        to_player_index=4,
        movies=tuple(replace(movie, action=action) for movie in bridge.movies),
    )
    result = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], following),
    ).to_runtime()
    assert isinstance(result, Unsupported)
    expected = "more than one bridge" if action == "bridge" else "actionable boundary follows a bridge"
    assert expected in result.reason


@pytest.mark.parametrize("include_later_restart", [False, True])
def test_to_runtime_refuses_bridge_before_restart(include_later_restart):
    plan = _plan()
    boundaries = (plan.boundaries[0], plan.boundaries[2])
    if include_later_restart:
        boundaries += (plan.boundaries[1],)
    result = replace(plan, boundaries=boundaries).to_runtime()
    assert isinstance(result, Unsupported)
    assert "precedes the first restart" in result.reason


def test_to_runtime_allows_empty_boundary_after_bridge():
    plan = _plan()
    empty = replace(plan.boundaries[3], to_player_index=4, movies=())
    result = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], empty),
    ).to_runtime()
    assert isinstance(result, dict)
    assert result == plan.to_runtime()


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


def _set_rotation(node, degrees):
    node["baseLayer"]["initialState"]["rotation"] = degrees


def _set_affine(node, matrix):
    node["baseLayer"]["initialState"]["affineTransform"] = matrix


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


def test_mixed_bridge_and_pin_cannot_bypass_qualified_plan():
    plan = _plan()
    extra = MovieContinuity('second.mov', 'pin', Rect(0, 0, 100, 100), Rect(0, 0, 100, 100))
    bridge = replace(plan.boundaries[2], movies=(*plan.boundaries[2].movies, extra))
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert 'pin action follows' in result.reason


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
        },
    )
    # the refusal lives on the boundary's own MovieContinuity too, and `action` still says pin.
    pinned = plan.boundaries[0].movies[0]
    assert pinned.action == "pin"
    assert pinned.refusal == plan.refusals[0]["reason"]
    # the 3->4 bridge's destination has nothing above the movie, so it is not refused.
    assert all(m.refusal is None for m in plan.boundaries[2].movies)


def test_fixture_runtime_plan_is_the_baseline_after_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.to_runtime() == EXPECTED_RUNTIME_PLAN


def test_refusals_are_not_part_of_the_runtime_plan():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert set(runtime) == {"movies", "boundaries"}
    assert "refusal" not in json.dumps(runtime)
    assert plan.as_dict()["refusals"] == [dict(r) for r in plan.refusals]
    assert json.loads(plan.to_json())["refusals"] == plan.as_dict()["refusals"]


def test_slide_instances_are_unchanged_by_the_refusal():
    """The refusal is a carry decision, not a geometry one: every authored instance is still
    ground truth for what must be visibly live on its slide."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances == {
        0: {"untitled.mov": [_rect(*SLIDE1_BIG), _rect(*SLIDE1_SMALL)]},
        1: {"untitled.mov": [_rect(*SLIDE1_BIG)]},
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
    assert [b["action"] for b in runtime["boundaries"]] == ["restart", "bridge"]


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


@pytest.mark.parametrize("gap", [0.0, 0.5, 1.0])
def test_artwork_touching_the_movies_edge_does_not_refuse(gap):
    """`_OVERLAP_MIN_PX` is 1.0 authored px and the intersection must be wider AND taller than
    it, so abutting edges and anti-aliasing seams are not a refusal."""
    x, y, w, _h = _rect_of_movie_on_slide2()

    def touch_only(data):
        data = _move_green_square_below_the_movie(data)
        _draw_slots(data, 0).append(_authored_slot(x + w - gap, y, 400.0, 400.0, object_id="TOUCH"))
        return data

    plan = _plan(_mutate_slide(SLIDE2, touch_only))
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()


def test_artwork_overlapping_by_more_than_the_minimum_refuses():
    x, y, w, _h = _rect_of_movie_on_slide2()

    def overlap_slightly(data):
        data = _move_green_square_below_the_movie(data)
        _draw_slots(data, 0).append(_authored_slot(x + w - 1.6, y, 400.0, 400.0, object_id="OVER"))
        return data

    plan = _plan(_mutate_slide(SLIDE2, overlap_slightly))
    assert isinstance(plan, ContinuityPlan)
    assert len(plan.refusals) == 1


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


def test_movie_slot_absent_in_every_event_is_refused():
    def drop_every_movie_slot(data):
        data = _move_green_square_below_the_movie(data)
        movie_id = _slot_object(data, 0, SLIDE2_GREEN_SLOT)["objectID"]
        for index in _events_drawing(data, movie_id):
            del _draw_slots(data, index)[SLIDE2_GREEN_SLOT]
        return data

    plan = _plan(_mutate_slide(SLIDE2, drop_every_movie_slot))
    assert isinstance(plan, Unsupported)
    assert "no draw slot" in plan.reason


def test_a_slot_above_the_movie_with_more_than_one_child_is_refused():
    def double_child(data):
        slot = _draw_slots(data, 0)[SLIDE2_GREEN_SLOT]
        slot["layers"] = slot["layers"] * 2
        return data

    plan = _plan(_mutate_slide(SLIDE2, double_child))
    assert isinstance(plan, Unsupported)
    assert "unrecognised slide layer shape" in plan.reason


def test_a_slide_with_no_draw_order_at_all_is_refused():
    def strip_base_layer(data):
        for event in data["events"]:
            event.pop("baseLayer")
        return data

    plan = _plan(_mutate_slide(SLIDE2, strip_base_layer))
    assert isinstance(plan, Unsupported)
    assert "no readable draw order" in plan.reason


def test_movie_node_without_an_object_id_is_refused():
    """Without an objectID the movie cannot be located in the draw order at all, so its
    z-position is unknown and nothing may be carried across the boundary."""

    def drop_object_id(data):
        return _map_movie_nodes(data, lambda node: node.pop("objectID"))

    plan = _plan(_mutate_slide(SLIDE2, drop_object_id))
    assert isinstance(plan, Unsupported)
    assert "no object id" in plan.reason


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


def test_masks_to_bounds_is_refused_as_a_possible_mask():
    def clip(node):
        node["baseLayer"]["initialState"]["masksToBounds"] = True

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, clip))
    assert plan.reason.endswith("masksToBounds")


def test_masks_to_bounds_on_the_video_sub_layer_is_refused_too():
    def clip(node):
        node["baseLayer"]["layers"][0]["initialState"]["masksToBounds"] = True

    _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, clip))


def test_a_non_unit_contents_rect_is_refused_as_a_possible_crop():
    def crop(node):
        node["baseLayer"]["layers"][0]["initialState"]["contentsRect"]["width"] = 0.5

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, crop))
    assert plan.reason.endswith("contentsRect")


def test_a_contents_rect_within_the_measurement_tolerance_is_not_refused():
    def jitter(node):
        node["baseLayer"]["layers"][0]["initialState"]["contentsRect"]["width"] = 1 - 5e-7

    plan = _plan(_mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, jitter)))
    assert isinstance(plan, ContinuityPlan)


def test_a_shape_path_anywhere_in_the_movie_subtree_is_refused():
    def shape(node):
        node["effects"] = [{"shapePath": {"elements": []}}]

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, shape))
    assert plan.reason.endswith("shapePath")


@pytest.mark.parametrize(
    "place",
    [
        pytest.param(lambda node: node.__setitem__("maskLayer", {}), id="node"),
        pytest.param(lambda node: node["baseLayer"].__setitem__("mask", {}), id="layer"),
        pytest.param(
            lambda node: node["baseLayer"]["initialState"].__setitem__("cornerRadius", 8),
            id="initialState",
        ),
        pytest.param(
            lambda node: node["baseLayer"]["layers"][0].__setitem__("mask", {}), id="video-layer",
        ),
    ],
)
def test_any_key_outside_the_measured_vocabulary_is_refused(place):
    _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, place))


def test_the_measured_vocabulary_does_not_refuse_todays_fixture():
    """The allowlist is only honest if it is a measurement: every key the fixture actually uses
    must be in it, or the rule would refuse the deck P2 qualified."""
    from obed_edom import live_continuity

    node_keys, layer_keys, state_keys = set(), set(), set()

    def walk(layer):
        layer_keys.update(layer)
        state_keys.update(layer["initialState"])
        for child in layer.get("layers") or []:
            walk(child)

    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        data = json.loads((FIXTURE_ROOT / "assets" / uuid / f"{uuid}.json").read_text())
        for node in _find_movie_nodes(data["events"]):
            node_keys.update(node)
            walk(node["baseLayer"])

    assert node_keys <= live_continuity._MOVIE_NODE_KEYS
    assert layer_keys <= live_continuity._MOVIE_LAYER_KEYS
    assert state_keys <= live_continuity._MOVIE_LAYER_STATE_KEYS
    assert "objectID" in node_keys, "the overlap rule needs the fixture's movie objectIDs"


def test_a_video_sub_layer_outside_its_movie_layer_is_refused():
    def push_out(node):
        node["baseLayer"]["layers"][0]["initialState"]["position"]["pointX"] += 200

    plan = _mask_reason_plan(SLIDE1, lambda data: _map_movie_nodes(data, push_out))
    assert plan.reason.endswith("the video sub-layer is not contained in its movie layer")


# --- `retire` in the runtime plan -----------------------------------------------------------


def _refused_pin(plan: ContinuityPlan, boundary_index: int, **changes):
    boundary = plan.boundaries[boundary_index]
    return replace(
        boundary,
        movies=tuple(replace(m, refusal="synthetic refusal") for m in boundary.movies),
        **changes,
    )


def test_a_refused_bridge_is_a_whole_deck_refusal():
    """`retire` is the only refusal the runtime can express, and only before the first cut. A
    bridge the destination slide covers is untested generality, so the whole deck falls back."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    refused_bridge = _refused_pin(plan, 2)
    result = replace(plan, boundaries=(*plan.boundaries[:2], refused_bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "cannot retire" in result.reason
    assert "synthetic refusal" in result.reason


def test_a_refused_bridge_derived_from_the_export_is_a_whole_deck_refusal():
    """The same thing end to end: put an object over the movie on slide 4, the 3->4 bridge's
    destination, and the deck stops qualifying altogether."""

    def cover_the_movie(data):
        movie_id = _slot_object(data, 0, 1)["objectID"]
        assert movie_id == "E4728E7D-2032-4D7F-83D6-8BE0EFB7B7BC"
        _draw_slots(data, 0).append(_authored_slot(*SLIDE4_UNTITLED, object_id="COVER"))
        return data

    plan = _plan(_mutate_slide(SLIDE4, cover_the_movie))
    assert isinstance(plan, ContinuityPlan)
    assert [r["toPlayer"] for r in plan.refusals] == [1, 3]
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)
    assert "cannot retire" in result.reason


def test_a_refusal_on_a_restart_boundary_is_a_whole_deck_refusal():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    refused_restart = _refused_pin(plan, 1)
    result = replace(plan, boundaries=(plan.boundaries[0], refused_restart, *plan.boundaries[2:])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "cannot retire" in result.reason


def test_two_refused_pin_boundaries_are_a_whole_deck_refusal():
    """The runtime honours one retire zone; a second is a shape it has never been measured on."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    second = _refused_pin(plan, 0, from_player_index=1, to_player_index=2)
    result = replace(plan, boundaries=(plan.boundaries[0], second, *plan.boundaries[2:])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "more than one retire boundary" in result.reason


def test_a_retire_after_a_restart_is_a_whole_deck_refusal():
    """The retire zone starts at the implicit pin zone, so it cannot open after a cut has
    already handed the movie back."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    carried = replace(
        plan.boundaries[0], movies=tuple(replace(m, refusal=None) for m in plan.boundaries[0].movies)
    )
    late = _refused_pin(plan, 0, from_player_index=2, to_player_index=3)
    result = replace(plan, boundaries=(carried, plan.boundaries[1], late)).to_runtime()
    assert isinstance(result, Unsupported)
    assert "follows a restart" in result.reason


def test_the_retire_precedes_the_restart_and_the_bridge_in_the_emitted_order():
    runtime = _plan().to_runtime()
    assert isinstance(runtime, dict)
    assert [b["action"] for b in runtime["boundaries"]] == ["retire", "restart", "bridge"]


# --- I5 codec report -----------------------------------------------------------------------

REAL_PLAYER_ROOT = Path(__file__).resolve().parents[1] / "output" / "p2-recovery" / "html-adversarial" / "html-player"


def test_codec_report_lists_every_referenced_movie_not_only_planned_ones():
    # The fixture's WA0125 instance never continues across a boundary (only Untitled.mov
    # does -- see test_boundary_3_to_4_bridges_the_moving_scaling_movie), so it is never
    # part of a continuity plan; the codec report must still list it.
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    assets = {entry["asset"] for entry in report}
    assert assets == {"untitled.mov", "vid-20250608-wa0125.mp4"}


def test_codec_report_entries_are_shaped_asset_codec_family_files():
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    for entry in report:
        assert set(entry) == {"asset", "codec", "family", "files"}


def test_codec_report_reports_none_for_a_movie_file_the_fixture_does_not_ship():
    # tests/fixtures/live_continuity ships only the export JSON, not the referenced
    # .mov bytes, so every entry must fail closed to an unreadable/"other" codec
    # rather than raising.
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    for entry in report:
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


def test_codec_report_aggregates_every_slide_folders_copy_of_one_asset():
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide(dict.fromkeys((SLIDE1, SLIDE2, SLIDE3, SLIDE4), "avc1"))
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": "avc1", "family": "h264", "files": 4,
    }


def test_codec_report_fails_closed_when_one_slide_folders_copy_is_a_different_codec():
    # Slide 1's copy is H.264 but slide 3's separate file is HEVC: keeping only the first
    # would report the key playable while a fresh decoder on slide 3 cannot play it.
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide({SLIDE1: "avc1", SLIDE2: "avc1", SLIDE3: "hvc1", SLIDE4: "avc1"})
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": None, "family": "other", "files": 4, "mixed": True,
    }


def test_codec_report_key_is_unreadable_when_any_of_its_files_is_unreadable():
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide({SLIDE1: "avc1", SLIDE2: "avc1", SLIDE3: None, SLIDE4: "avc1"})
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    # unreadable, not "mixed": the key's codec is simply unknown.
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": None, "family": "other", "files": 4,
    }


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


def test_slide_instances_lists_both_untitled_instances_on_slide_1():
    """Slide 1 (player index 0) authors two Untitled.mov instances: the big continuing one
    and the second, non-continuing one at ~(1076, 876) that `slide_rects` drops entirely."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert set(plan.slide_instances[0]) == {"untitled.mov"}
    assert plan.slide_instances[0]["untitled.mov"] == [_rect(*SLIDE1_BIG), _rect(*SLIDE1_SMALL)]
    # the same slide contributes nothing to slide_rects, which drops multi-instance assets.
    assert plan.slide_rects[0] == {}


def test_slide_instances_matches_slide_rects_where_an_asset_is_single_instance():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    for player_index, rects in plan.slide_rects.items():
        for asset, rect in rects.items():
            assert plan.slide_instances[player_index][asset] == [rect]


def test_slide_instances_lists_the_never_planned_wa0125_movie_on_slide_3():
    """WA0125 never continues across a boundary, so it appears in no MovieContinuity and in
    no runtime movie table -- but it is authored on slide 3 and must be visibly live there."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances[2] == {
        "untitled.mov": [_rect(*SLIDE3_UNTITLED)],
        "vid-20250608-wa0125.mp4": [_rect(*SLIDE3_WA0125)],
    }


def test_slide_instances_lists_only_the_moved_scaled_movie_on_slide_4():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances[3] == {"untitled.mov": [_rect(*SLIDE4_UNTITLED)]}


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


def test_slide_instances_round_trips_through_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    restored = json.loads(plan.to_json())
    assert restored == plan.as_dict()
    assert restored["slideInstances"]["0"]["untitled.mov"] == [
        _rect(*SLIDE1_BIG),
        _rect(*SLIDE1_SMALL),
    ]
    assert list(restored["slideInstances"]) == ["0", "1", "2", "3"]


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
    assert set(runtime) == {"movies", "boundaries"}
    assert "slideInstances" not in json.dumps(runtime)
    assert "slide_instances" not in json.dumps(runtime)
    assert live_continuity.plan_signature(runtime) == EXPECTED_PLAN_SHA256
    assert live_continuity.plan_signature(runtime) in live_continuity.QUALIFIED_PLAN_SHA256
    # an emptied field must not change the runtime either.
    assert replace(plan, slide_instances={}).to_runtime() == runtime


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_slide_instances_match_the_trimmed_fixture():
    def resolver(root: Path, relative: str) -> Path:
        return root / relative

    real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=resolver)
    fixture = _plan()
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.slide_instances == fixture.slide_instances


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_movies_report_h264():
    def resolver(root: Path, relative: str) -> Path:
        return root / relative

    report = codec_report(REAL_PLAYER_ROOT, SLIDES, resolver=resolver)
    assert report
    for entry in report:
        assert entry["codec"] == "avc1"
        assert entry["family"] == "h264"
    # the export stores its own copy of Untitled.mov under each of the four slide folders,
    # and every one of them is probed.
    assert next(entry for entry in report if entry["asset"] == "untitled.mov")["files"] == 4


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_yields_the_same_runtime_plan_and_refusal():
    """The trimmed fixture gained the draw-slot data the overlap rule reads; this is the check
    that it was copied faithfully, not authored to suit the rule."""
    real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=lambda root, relative: root / relative)
    assert isinstance(real, ContinuityPlan)
    assert real.to_runtime() == EXPECTED_RUNTIME_PLAN
    fixture = _plan()
    assert isinstance(fixture, ContinuityPlan)
    assert real.refusals == fixture.refusals
