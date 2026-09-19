from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan

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
        events[0]["effects"][0]["effects"] = events[0]["effects"][0].get("effects", []) + [
            {"movie": clone["movie"], "baseLayer": clone["baseLayer"], "effects": []}
        ]
        data = {**data, "events": events}
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
